from __future__ import annotations

import json
import locale
import queue
import sys
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QStackedWidget,
)

from autocruise.application.live_planner import LiveActionPlanner
from autocruise.application.orchestrator import SessionOrchestrator
from autocruise.domain.models import (
    AdapterMode,
    ScheduleKind,
    ScheduledJob,
    ScheduledJobState,
    SessionState,
    utc_now,
)
from autocruise.infrastructure.codex_app_server import (
    CodexAccountState,
    CodexAppServerConnection,
    CodexAppServerError,
    CodexModelProfile,
    read_cached_auth_mode,
)
from autocruise.infrastructure.automation import AutomationRouter
from autocruise.infrastructure.browser.playwright_adapter import PlaywrightAdapter
from autocruise.infrastructure.browser.sensor import BrowserSensorHub
from autocruise.infrastructure.ipc import LocalCommandServer
from autocruise.infrastructure.mock import MockAgentToolset
from autocruise.infrastructure.providers import ProviderError, ProviderRegistry
from autocruise.infrastructure.storage import (
    ProviderSettingsRepository,
    ScheduledJobRepository,
    SecureSecretStore,
    WorkspacePaths,
    append_jsonl,
    load_structured,
    read_text,
    write_text_file,
)
from autocruise.infrastructure.windows.input_executor import InputExecutor
from autocruise.infrastructure.windows.global_hotkeys import GlobalHotkeyManager, normalize_hotkey
from autocruise.infrastructure.windows.observation_builder import WindowsObservationBuilder
from autocruise.infrastructure.windows.screenshot_provider import ScreenshotProvider
from autocruise.infrastructure.windows.session_state import is_workstation_locked
from autocruise.infrastructure.windows.task_scheduler import TaskSchedulerError, WindowsTaskSchedulerService, schedule_next_run
from autocruise.infrastructure.windows.toolset import WindowsAgentToolset
from autocruise.infrastructure.windows.uia_adapter import UIAAdapter
from autocruise.infrastructure.windows.window_manager import WindowManager
from autocruise.presentation.data_sources import (
    build_knowledge_items,
    delete_session_thread,
    load_scheduled_jobs,
    load_session_detail,
    load_session_history,
)
from autocruise.presentation.labels import (
    friendly_app_name,
    friendly_flow,
    friendly_result,
    friendly_state,
    friendly_state_hint,
    sanitize_user_message,
    set_locale,
    status_key_from_label,
    translation_key_for_text,
    tr,
)
from autocruise.presentation.ui.components import AppButton, AppTextEditor, Card, SidebarItem, StatusBadge
from autocruise.presentation.ui.icons import app_icon, nav_icon
from autocruise.presentation.ui.pages.history_page import HistoryPage
from autocruise.presentation.ui.pages.home_page import HomePage
from autocruise.presentation.ui.pages.knowledge_page import KnowledgePage
from autocruise.presentation.ui.pages.schedules_page import SchedulesPage
from autocruise.presentation.ui.pages.settings_page import SettingsPage
from autocruise.presentation.ui.theme import apply_theme
from autocruise.presentation.ui.tokens import COLORS, SIDEBAR_WIDTH, SPACE
from autocruise.version import APP_TITLE, APP_VERSION, COMPANY_NAME


def _default_language() -> str:
    language_code, _ = locale.getdefaultlocale()
    return "ja" if (language_code or "").lower().startswith("ja") else "en"


DEFAULT_PREFERENCES = {
    "language": _default_language(),
    "screenshot_ttl_days": 3,
    "keep_important_screenshots_days": 14,
    "default_adapter_mode": AdapterMode.WINDOWS.value,
    "autonomy_mode": "autonomous",
    "max_steps_limit_enabled": False,
    "max_steps_per_session": None,
    "history_display_limit": 120,
    "pause_hotkey": "F8",
    "stop_hotkey": "F12",
    "selected_system_prompt": "",
    "system_prompt_selection_initialized": True,
    "show_onboarding_on_start": False,
    "onboarding_completed": True,
}

LEGACY_PREFERENCE_KEYS = {
    "allow_image_send",
    "default_provider",
    "keep_high_risk_screenshots_days",
    "live_planner_preferred",
    "ui",
}


def normalize_preferences(raw_preferences: dict | None) -> dict:
    migrated_legacy_system_prompt_default = (
        raw_preferences is not None
        and "system_prompt_selection_initialized" not in raw_preferences
        and str(raw_preferences.get("selected_system_prompt", "") or "").strip() == "AutoCruise.md"
    )
    merged = {**DEFAULT_PREFERENCES, **(raw_preferences or {})}
    if migrated_legacy_system_prompt_default:
        merged["selected_system_prompt"] = ""
    merged["system_prompt_selection_initialized"] = True
    if raw_preferences and "keep_important_screenshots_days" not in raw_preferences:
        if "keep_high_risk_screenshots_days" in raw_preferences:
            merged["keep_important_screenshots_days"] = raw_preferences["keep_high_risk_screenshots_days"]
    for key in LEGACY_PREFERENCE_KEYS:
        merged.pop(key, None)

    mode = str(merged.get("default_adapter_mode", AdapterMode.WINDOWS.value) or AdapterMode.WINDOWS.value)
    if mode not in {AdapterMode.MOCK.value, AdapterMode.WINDOWS.value}:
        mode = AdapterMode.WINDOWS.value
    if mode == AdapterMode.MOCK.value:
        mode = AdapterMode.WINDOWS.value
    merged["default_adapter_mode"] = mode
    autonomy_mode = str(merged.get("autonomy_mode", "autonomous") or "autonomous").strip().lower()
    merged["autonomy_mode"] = autonomy_mode if autonomy_mode in {"balanced", "autonomous"} else "autonomous"
    merged["max_steps_limit_enabled"] = False
    merged["max_steps_per_session"] = None
    merged["pause_hotkey"] = normalize_hotkey(str(merged.get("pause_hotkey", "F8") or ""))
    merged["stop_hotkey"] = normalize_hotkey(str(merged.get("stop_hotkey", "F12") or ""))
    return merged


def finish_visibility_action(*, backgrounded: bool, trigger: str, tray_available: bool) -> str:
    if not backgrounded:
        return "none"
    if trigger == "manual" or not tray_available:
        return "show_main"
    return "notify_tray"


def build_product_footer(version: str, company_name: str) -> tuple[str, str]:
    return (
        f"AutoCruise Codex Edition Version {version}",
        f"Created by {company_name}",
    )


def notice_label_style(tone: str) -> str:
    color_map = {
        "info": COLORS.text_secondary,
        "success": COLORS.success,
        "warning": COLORS.warning,
        "error": COLORS.danger,
    }
    color = color_map.get(tone, COLORS.text_secondary)
    return f"color: {color}; font-size: 12px; background: transparent;"


def button_text_with_shortcut(label: str, hotkey: str) -> str:
    hotkey_text = str(hotkey or "").strip()
    return f"{label} ({hotkey_text})" if hotkey_text else label


def compact_panel_copy(text: str, max_chars: int) -> tuple[str, str]:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized, ""
    shortened = normalized[: max(0, max_chars - 1)].rstrip()
    return f"{shortened}…", normalized


class FloatingControlWidget(QWidget):
    open_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(f"{APP_TITLE} Controls")
        self.resize(452, 244)
        self.setMinimumSize(408, 228)
        self._full_goal_text = ""
        self._full_activity_text = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card()
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.logo_label = QLabel()
        self.logo_label.setStyleSheet("background: transparent;")
        self.logo_label.setPixmap(app_icon(size=48).pixmap(30, 30))
        self.logo_label.setFixedSize(30, 30)
        self.logo_label.setScaledContents(True)
        header.addWidget(self.logo_label, 0, Qt.AlignVCenter)
        self.title_label = QLabel(APP_TITLE)
        self.title_label.setStyleSheet(f"color: {COLORS.text_primary}; font-size: 21px; font-weight: 300; background: transparent;")
        header.addWidget(self.title_label, 0, Qt.AlignVCenter)
        header.addStretch(1)
        self.status_badge = StatusBadge(tr("status.ready"), "ready")
        header.addWidget(self.status_badge, 0, Qt.AlignRight)
        layout.addLayout(header)

        self.goal_label = QLabel(tr("message.goal_idle"))
        self.goal_label.setProperty("role", "body")
        self.goal_label.setWordWrap(True)
        self.goal_label.setMaximumHeight(54)
        self.goal_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.goal_label)

        self.activity_label = QLabel(tr("message.home_empty"))
        self.activity_label.setProperty("role", "muted")
        self.activity_label.setWordWrap(True)
        self.activity_label.setMaximumHeight(66)
        self.activity_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.activity_label)

        actions = QHBoxLayout()
        self.open_button = AppButton(tr("button.open"), "secondary")
        self.pause_button = AppButton(tr("button.pause"), "secondary")
        self.stop_button = AppButton(tr("button.stop"), "danger")
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)

        self.open_button.clicked.connect(self.open_requested.emit)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.hide()

    def set_goal(self, text: str) -> None:
        self._full_goal_text = text or tr("message.goal_idle")
        compact_text, tooltip = compact_panel_copy(self._full_goal_text, 140)
        self.goal_label.setText(compact_text)
        self.goal_label.setToolTip(tooltip)

    def set_status(self, badge: str, tone: str, activity: str) -> None:
        self.status_badge.setText(badge)
        self.status_badge.set_tone(tone)
        self._full_activity_text = activity
        compact_text, tooltip = compact_panel_copy(activity, 180)
        self.activity_label.setText(compact_text)
        self.activity_label.setToolTip(tooltip)

    def set_pause_label(self, text: str) -> None:
        self.pause_button.setText(text)

    def set_stop_label(self, text: str) -> None:
        self.stop_button.setText(text)

    def set_logo_pixmap(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        self.logo_label.setPixmap(pixmap)

    def retranslate(self) -> None:
        self.open_button.setText(tr("button.open"))
        self.pause_button.setText(tr("button.pause"))
        self.stop_button.setText(tr("button.stop"))

    def present(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            self.move(geometry.right() - self.width() - 24, geometry.bottom() - self.height() - 24)
        self.show()
        self.raise_()
        self.activateWindow()


class MainWindow(QMainWindow):
    def __init__(
        self,
        workspace_root: Path,
        data_root: Path | None = None,
        pending_task_id: str = "",
        start_hidden: bool = False,
    ) -> None:
        super().__init__()
        self.paths = WorkspacePaths(workspace_root, data_root=data_root)
        self.paths.ensure()
        self.provider_repo = ProviderSettingsRepository(self.paths)
        self.job_repo = ScheduledJobRepository(self.paths)
        self.secret_store = SecureSecretStore(self.paths)
        self.codex_app_server = CodexAppServerConnection(self.paths.root)
        self.provider_registry = ProviderRegistry(self.paths.root, codex_app_server=self.codex_app_server)
        self.task_scheduler = WindowsTaskSchedulerService()
        self.preferences = self._load_preferences()
        self.pending_system_prompt_selection: str | None = None
        self.logo_path = self.paths.root / "autocruise_logo.png"
        self.brand_icon = self._load_app_icon()
        set_locale(self.preferences.get("language", "en"))

        self.event_queue: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.command_server = LocalCommandServer(self.paths.root, self._queue_command)
        self.worker: threading.Thread | None = None
        self.selected_history_id = ""
        self.history_records: list[dict] = []
        self.schedule_records: list[dict] = []
        self.knowledge_data: dict[str, list[dict]] = {}
        self.selected_knowledge_item: dict | None = None
        self.current_status = tr("status.ready")
        self.current_status_key = "status.ready"
        self.current_tone = "ready"
        self.current_activity = ""
        self.current_connection = ""
        self.current_goal = ""
        self.active_task_id = ""
        self.active_trigger = "manual"
        self._backgrounded_run = False
        self.current_page = "home"
        self.pending_task_id = pending_task_id
        self.start_hidden = start_hidden
        self.pending_task_queue: deque[str] = deque()
        self._codex_result_message = ""
        self._pending_login_id = ""
        self._codex_models: list[CodexModelProfile] = []
        self.sidebar_buttons: dict[str, SidebarItem] = {}
        self.sidebar_icons: dict[str, tuple] = {}

        self.home_page = HomePage()
        self.history_page = HistoryPage()
        self.knowledge_page = KnowledgePage()
        self.schedules_page = SchedulesPage()
        self.settings_page = SettingsPage()
        self.floating_controls: FloatingControlWidget | None = None

        self.tray_icon: QSystemTrayIcon | None = None
        self.tray_open_action: QAction | None = None
        self.tray_settings_action: QAction | None = None
        self.tray_controls_action: QAction | None = None
        self.tray_pause_action: QAction | None = None
        self.tray_stop_action: QAction | None = None
        self.tray_quit_action: QAction | None = None
        self._tray_notice_sent = False
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self._clear_notice)
        self.hotkey_manager = GlobalHotkeyManager()
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self.hotkey_manager)
        self.hotkey_manager.activated.connect(self._handle_global_hotkey)

        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(self.brand_icon)
        self.resize(1120, 760)
        self.setMinimumSize(820, 600)

        self._build_ui()
        self._connect_pages()
        self._initialize_tray()
        self._refresh_hotkeys(show_feedback=False)
        self.command_server.start()
        self._refresh_settings()
        self._refresh_history()
        self._refresh_schedules()
        self._refresh_knowledge()
        self._update_connection_state()

        self.orchestrator = SessionOrchestrator(
            self.paths,
            toolset_factory=self._create_toolset,
            event_sink=lambda kind, payload: self.event_queue.put((kind, payload)),
        )
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._pump_events)
        self.timer.start(120)
        self._refresh_compact_surfaces()
        if self.pending_task_id:
            QTimer.singleShot(250, lambda: self._enqueue_scheduled_task(self.pending_task_id))

    def _load_preferences(self) -> dict:
        merged = normalize_preferences(load_structured(self.paths.preferences_path()))
        write_text_file(self.paths.preferences_path(), json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return merged

    def _save_preferences(self) -> None:
        write_text_file(self.paths.preferences_path(), json.dumps(self.preferences, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_app_icon(self) -> QIcon:
        if self.logo_path.exists():
            icon = QIcon(str(self.logo_path))
            if not icon.isNull():
                return icon
        return app_icon()

    def _load_brand_pixmap(self, size: int = 40) -> QPixmap:
        if self.logo_path.exists():
            pixmap = QPixmap(str(self.logo_path))
            if not pixmap.isNull():
                return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return self.brand_icon.pixmap(size, size)

    def _ensure_floating_controls(self) -> FloatingControlWidget:
        if self.floating_controls is None:
            controls = FloatingControlWidget()
            controls.set_logo_pixmap(self._load_brand_pixmap(30))
            controls.open_requested.connect(self._show_main_window)
            controls.pause_requested.connect(self._toggle_pause)
            controls.stop_requested.connect(self._stop_session)
            self.floating_controls = controls
        return self.floating_controls

    def _hide_floating_controls(self) -> None:
        if self.floating_controls is not None:
            self.floating_controls.hide()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(SPACE.md, SPACE.md, SPACE.md, SPACE.md)
        layout.setSpacing(SPACE.md)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        layout.addWidget(splitter, 1)

        self.sidebar = QFrame()
        self.sidebar.setProperty("sidebar", True)
        self.sidebar.setMinimumWidth(220)
        self.sidebar.setMaximumWidth(240)
        self.sidebar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(SPACE.md, SPACE.md, SPACE.md, SPACE.md)
        sidebar_layout.setSpacing(SPACE.md)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(8)
        self.sidebar_logo = QLabel()
        self.sidebar_logo.setFixedSize(40, 40)
        self.sidebar_logo.setPixmap(self._load_brand_pixmap(40))
        brand_row.addWidget(self.sidebar_logo, 0, Qt.AlignVCenter)

        self.sidebar_title = QLabel(APP_TITLE)
        self.sidebar_title.setProperty("role", "brand")
        brand_row.addWidget(self.sidebar_title, 1, Qt.AlignVCenter)
        sidebar_layout.addLayout(brand_row)

        nav_container = QVBoxLayout()
        nav_container.setSpacing(6)
        sidebar_layout.addLayout(nav_container)
        for key, label_key, icon_name in (
            ("home", "sidebar.new_thread", "spark"),
            ("knowledge", "tab.knowledge", "knowledge"),
            ("schedules", "tab.schedules", "calendar"),
            ("threads", "tab.history", "history"),
            ("settings", "tab.settings", "settings"),
        ):
            inactive = nav_icon(icon_name, COLORS.text_secondary)
            active = nav_icon(icon_name, COLORS.accent)
            button = SidebarItem(tr(label_key), inactive)
            button.clicked.connect(lambda _checked=False, value=key: self._handle_sidebar_action(value))
            nav_container.addWidget(button)
            self.sidebar_buttons[key] = button
            self.sidebar_icons[key] = (inactive, active)

        sidebar_layout.addStretch(1)

        splitter.addWidget(self.sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 0, 28, 0)
        content_layout.setSpacing(SPACE.md)

        self.header_widget = QWidget()
        header = QVBoxLayout(self.header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        self.page_title = QLabel("")
        self.page_title.setProperty("role", "title")
        self.page_title.setStyleSheet("font-size: 22px;")
        header.addWidget(self.page_title)
        content_layout.addWidget(self.header_widget)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.knowledge_page)
        self.stack.addWidget(self.schedules_page)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.settings_page)
        content_layout.addWidget(self.stack, 1)

        footer_widget = QWidget()
        footer_layout = QVBoxLayout(footer_widget)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(2)
        self.notice_label = QLabel("")
        self.notice_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.notice_label.setWordWrap(True)
        self.notice_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.notice_label.setStyleSheet(notice_label_style("info"))
        self.notice_label.hide()
        footer_layout.addWidget(self.notice_label)

        self.product_footer_label = QLabel("")
        self.product_footer_label.setProperty("role", "muted")
        self.product_footer_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.product_footer_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        footer_layout.addWidget(self.product_footer_label)

        self.creator_footer_label = QLabel("")
        self.creator_footer_label.setProperty("role", "muted")
        self.creator_footer_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.creator_footer_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        footer_layout.addWidget(self.creator_footer_label)
        content_layout.addWidget(footer_widget)
        self._refresh_footer_copy()

        splitter.addWidget(content)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([SIDEBAR_WIDTH, 880])

        self._select_page("home")

    def _connect_pages(self) -> None:
        self.home_page.run_requested.connect(self._start_session)
        self.home_page.pause_requested.connect(self._toggle_pause)
        self.home_page.stop_requested.connect(self._stop_session)

        self.history_page.diagnostics_requested.connect(self._open_history_diagnostics)
        self.history_page.delete_requested.connect(self._delete_selected_thread)
        self.history_page.selected_requested.connect(self._show_history_payload)
        self.knowledge_page.detail_requested.connect(self._open_knowledge_detail)
        self.knowledge_page.create_requested.connect(self._create_knowledge_item)
        self.knowledge_page.list_panel.selected_payload.connect(self._show_knowledge_payload)
        self.schedules_page.new_requested.connect(self._new_schedule)
        self.schedules_page.save_requested.connect(self._save_schedule)
        self.schedules_page.enable_requested.connect(self._enable_schedule)
        self.schedules_page.disable_requested.connect(self._disable_schedule)
        self.schedules_page.delete_requested.connect(self._delete_schedule)

        self.settings_page.save_general_requested.connect(self._save_general_settings)
        self.settings_page.save_ai_requested.connect(self._save_ai_settings)
        self.settings_page.sign_in_requested.connect(self._sign_in_with_chatgpt)
        self.settings_page.sign_out_requested.connect(self._sign_out_codex)
        self.settings_page.save_storage_requested.connect(self._save_storage_settings)
        self.settings_page.purge_requested.connect(self._purge_screenshots)
        self.settings_page.new_system_prompt_requested.connect(self._new_system_prompt)
        self.settings_page.edit_system_prompt_requested.connect(self._edit_system_prompt)
        self.settings_page.open_system_prompt_folder_requested.connect(self._open_system_prompt_folder)
        self.settings_page.open_screenshots_requested.connect(self._open_screenshots_folder)
        self.settings_page.language_changed.connect(self._change_language)
        self.settings_page.system_prompt_changed.connect(self._remember_system_prompt_selection)

    def _initialize_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self.brand_icon, self)
        self.tray_icon.setToolTip(APP_TITLE)
        menu = QMenu(self)
        self.tray_open_action = QAction(tr("tray.show_main"), self)
        self.tray_settings_action = QAction(tr("tab.settings"), self)
        self.tray_controls_action = QAction(tr("tray.show_controls"), self)
        self.tray_pause_action = QAction(tr("tray.pause"), self)
        self.tray_stop_action = QAction(tr("tray.stop"), self)
        self.tray_quit_action = QAction(tr("tray.quit"), self)

        self.tray_open_action.triggered.connect(self._show_main_window)
        self.tray_settings_action.triggered.connect(self._open_settings_page)
        self.tray_controls_action.triggered.connect(self._show_floating_controls)
        self.tray_pause_action.triggered.connect(self._toggle_pause)
        self.tray_stop_action.triggered.connect(self._stop_session)
        self.tray_quit_action.triggered.connect(self._quit_application)

        for action in (
            self.tray_open_action,
            self.tray_settings_action,
            self.tray_controls_action,
            self.tray_pause_action,
            self.tray_stop_action,
        ):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self.tray_quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger}:
            self._show_main_window()

    def _handle_sidebar_action(self, key: str) -> None:
        if key == "home":
            self._start_new_thread()
            return
        self._select_page(key)

    def _start_new_thread(self) -> None:
        self._select_page("home")
        if not self._is_session_active():
            self.current_goal = ""
            self.home_page.goal_input.clear()
            self.home_page.set_goal("")

    def _select_page(self, key: str) -> None:
        order = {"home": 0, "knowledge": 1, "schedules": 2, "threads": 3, "settings": 4}
        self.current_page = key
        self.stack.setCurrentIndex(order[key])
        self.page_title.setText("")
        self.header_widget.hide()
        for name, button in self.sidebar_buttons.items():
            checked = name == key
            button.setChecked(checked)
            inactive, active = self.sidebar_icons[name]
            button.setIcon(active if checked else inactive)

    def _is_session_active(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _refresh_compact_surfaces(self) -> None:
        self.home_page.set_goal(self.current_goal)
        self.home_page.set_status(self.current_status, self.current_tone, self.current_activity, self.current_connection)
        if self.floating_controls is not None:
            self.floating_controls.set_goal(self.current_goal)
            self.floating_controls.set_status(self.current_status, self.current_tone, self.current_activity)
        self._update_pause_controls()
        self._update_tray_state()

    def _set_goal(self, text: str) -> None:
        self.current_goal = text.strip()
        self.home_page.set_goal(self.current_goal)
        if self.floating_controls is not None:
            self.floating_controls.set_goal(self.current_goal)
        self._update_tray_state()

    def _set_status(self, badge: str, tone: str, activity: str, connection: str) -> None:
        self.current_status = badge
        self.current_status_key = status_key_from_label(badge)
        self.current_tone = tone
        self.current_activity = "" if tone == "ready" else activity
        self.current_connection = connection
        self.home_page.set_status(badge, tone, activity, connection)
        if self.floating_controls is not None:
            self.floating_controls.set_status(badge, tone, self.current_activity)
        self._update_tray_state()

    def _set_activity(self, text: str) -> None:
        if self.current_tone == "ready":
            self.current_activity = ""
        elif text:
            self.current_activity = text
        self.home_page.set_next_action(self.current_activity)
        if self.floating_controls is not None:
            self.floating_controls.set_status(self.current_status, self.current_tone, self.current_activity)
        self._update_tray_state()

    def _translate_known_text(self, text: str, *, prefixes: tuple[str, ...]) -> str:
        key = translation_key_for_text(text, prefixes=prefixes)
        return tr(key) if key else text

    def _refresh_footer_copy(self) -> None:
        product_text, creator_text = build_product_footer(APP_VERSION, COMPANY_NAME)
        self.product_footer_label.setText(product_text)
        self.creator_footer_label.setText(creator_text)

    def _show_notice(
        self,
        message: str,
        *,
        tone: str = "info",
        timeout_ms: int = 5000,
        show_tray: bool = False,
    ) -> None:
        text = message.strip()
        if not text:
            self._clear_notice()
            return
        self.notice_label.setText(text)
        self.notice_label.setStyleSheet(notice_label_style(tone))
        self.notice_label.show()
        self.notice_timer.stop()
        if timeout_ms > 0:
            self.notice_timer.start(timeout_ms)
        if show_tray and self.tray_icon is not None and (self._backgrounded_run or not self.isVisible()):
            self.tray_icon.showMessage(APP_TITLE, text)

    def _clear_notice(self) -> None:
        self.notice_timer.stop()
        if hasattr(self, "notice_label"):
            self.notice_label.clear()
            self.notice_label.hide()

    def _update_pause_controls(self) -> None:
        paused = self.current_status_key == "status.paused"
        pause_hotkey = str(self.preferences.get("pause_hotkey", "") or "").strip()
        stop_hotkey = str(self.preferences.get("stop_hotkey", "") or "").strip()
        pause_text = tr("button.resume") if paused else tr("button.pause")
        stop_text = tr("button.stop")
        tray_text = tr("tray.resume") if paused else tr("tray.pause")
        self.home_page.set_pause_label(button_text_with_shortcut(pause_text, pause_hotkey))
        self.home_page.set_stop_label(button_text_with_shortcut(stop_text, stop_hotkey))
        if self.floating_controls is not None:
            self.floating_controls.set_pause_label(button_text_with_shortcut(pause_text, pause_hotkey))
            self.floating_controls.set_stop_label(button_text_with_shortcut(stop_text, stop_hotkey))
        if self.tray_pause_action is not None:
            self.tray_pause_action.setText(tray_text)
            self.tray_pause_action.setEnabled(self._is_session_active())
        if self.tray_stop_action is not None:
            self.tray_stop_action.setEnabled(self._is_session_active())

    def _update_tray_state(self) -> None:
        if self.tray_icon is None:
            return
        goal = self.current_goal or tr("message.tray_ready")
        self.tray_icon.setToolTip(f"{APP_TITLE}\n{self.current_status}\n{goal}")
        if self.tray_controls_action is not None:
            self.tray_controls_action.setEnabled(self._is_session_active())

    def _handle_global_hotkey(self, action_name: str) -> None:
        if action_name == "pause":
            self._toggle_pause()
        elif action_name == "stop":
            self._stop_session()

    def _refresh_hotkeys(self, *, show_feedback: bool) -> None:
        failures = self.hotkey_manager.apply_bindings(
            {
                "pause": self.preferences.get("pause_hotkey", ""),
                "stop": self.preferences.get("stop_hotkey", ""),
            }
        )
        if failures and show_feedback:
            self._show_notice(
                tr("message.hotkeys_partial", shortcuts=", ".join(failures)),
                tone="warning",
                timeout_ms=7000,
            )

    def _background_shortcut_message(self) -> str:
        pause_hotkey = self.preferences.get("pause_hotkey", "")
        stop_hotkey = self.preferences.get("stop_hotkey", "")
        if pause_hotkey and stop_hotkey:
            return tr("message.moved_to_tray_shortcuts", pause=pause_hotkey, stop=stop_hotkey)
        return tr("message.moved_to_tray")

    def _queue_command(self, payload: dict) -> None:
        self.event_queue.put(("command", payload))

    def _run_session_worker(self, instruction: str, task_id: str, trigger: str) -> None:
        try:
            snapshot = self.orchestrator.run(instruction, task_id=task_id, trigger=trigger)
            self.event_queue.put(("worker_done", {"snapshot": snapshot, "task_id": task_id, "trigger": trigger}))
        except Exception as exc:  # noqa: BLE001
            message = sanitize_user_message(str(exc)) or tr("message.run_internal_error")
            self.event_queue.put(
                (
                    "worker_failed",
                    {
                        "message": message,
                        "task_id": task_id,
                        "trigger": trigger,
                    },
                )
            )

    def _start_session_internal(
        self,
        instruction: str,
        *,
        task_id: str = "",
        trigger: str = "manual",
        move_to_background: bool = True,
    ) -> bool:
        if self._is_session_active():
            return False
        if not instruction:
            return False
        self._tray_notice_sent = False
        self.active_task_id = task_id
        self.active_trigger = trigger
        self._backgrounded_run = False
        self._set_goal(instruction)
        self.home_page.set_running(True)
        self._set_status(tr("status.loading"), "running", tr("message.running"), self.current_connection)
        self.worker = threading.Thread(
            target=self._run_session_worker,
            args=(instruction, task_id, trigger),
            daemon=True,
        )
        self.worker.start()
        if task_id:
            self.job_repo.record_result(task_id, ScheduledJobState.RUNNING, tr("schedule.state.running"), utc_now())
            self._refresh_schedules()
        if move_to_background:
            QTimer.singleShot(250, self._move_to_background)
        return True

    def _enqueue_scheduled_task(self, task_id: str) -> None:
        if not task_id:
            return
        if task_id == self.active_task_id or task_id in self.pending_task_queue:
            return
        if self._is_session_active():
            self.pending_task_queue.append(task_id)
            self._log_schedule_event(task_id, "queued", "Queued behind the current run.")
            if self.tray_icon is not None:
                self.tray_icon.showMessage(APP_TITLE, tr("message.schedule_queued"))
            return
        self._start_scheduled_task(task_id)

    def _start_scheduled_task(self, task_id: str) -> None:
        job = self.job_repo.get(task_id)
        if job is None:
            self._log_schedule_event(task_id, "missing", tr("message.schedule_not_found"))
            return
        if not job.enabled:
            self._skip_scheduled_task(job, tr("message.schedule_disabled"))
            return
        if is_workstation_locked():
            self._skip_scheduled_task(job, tr("message.schedule_locked"))
            return
        blocked_message = self._default_run_block_message()
        if blocked_message:
            self._fail_scheduled_task(job, blocked_message)
            return
        started = self._start_session_internal(
            job.instruction,
            task_id=job.task_id,
            trigger="scheduled",
            move_to_background=True,
        )
        if not started:
            self.pending_task_queue.appendleft(job.task_id)

    def _start_next_queued_task(self) -> None:
        if self._is_session_active():
            return
        while self.pending_task_queue:
            task_id = self.pending_task_queue.popleft()
            job = self.job_repo.get(task_id)
            if job is None:
                continue
            self._start_scheduled_task(task_id)
            if self._is_session_active():
                break

    def _skip_scheduled_task(self, job: ScheduledJob, message: str) -> None:
        ran_at = utc_now()
        recorded = self.job_repo.record_result(job.task_id, ScheduledJobState.SKIPPED, message, ran_at) or job
        self._reschedule_recurring_job(recorded, consume_current=True)
        self._append_schedule_history(job, message, ran_at, "skipped")
        self._log_schedule_event(job.task_id, "skipped", message)
        self._refresh_history()
        self._refresh_schedules()

    def _fail_scheduled_task(self, job: ScheduledJob, message: str) -> None:
        ran_at = utc_now()
        recorded = self.job_repo.record_result(job.task_id, ScheduledJobState.FAILED, message, ran_at) or job
        self._reschedule_recurring_job(recorded, consume_current=True)
        self._append_schedule_history(job, message, ran_at, "failed")
        self._log_schedule_event(job.task_id, "failed", message)
        self._refresh_history()
        self._refresh_schedules()
        if self.tray_icon is not None:
            self.tray_icon.showMessage(APP_TITLE, message)

    def _append_schedule_history(self, job: ScheduledJob, message: str, ran_at: str, result: str) -> None:
        append_jsonl(
            self.paths.logs_dir / "session_history.jsonl",
            {
                "session_id": uuid.uuid4().hex[:8],
                "executed_at": ran_at,
                "completed_at": ran_at,
                "instruction": job.instruction,
                "task_id": job.task_id,
                "trigger": "scheduled",
                "target_app": "general",
                "result": result,
                "step_count": 0,
                "message": message,
                "failure_reason": message,
                "important_confirmations": [],
                "used_context": [],
                "saved_captures": [],
                "flow": ["scheduled"],
            },
        )

    def _record_job_completion(self, snapshot, task_id: str, trigger: str) -> None:
        if not task_id:
            return
        result_map = {
            SessionState.COMPLETED: ScheduledJobState.COMPLETED,
            SessionState.FAILED: ScheduledJobState.FAILED,
            SessionState.STOPPED: ScheduledJobState.FAILED,
        }
        result = result_map.get(snapshot.state, ScheduledJobState.FAILED)
        message = getattr(snapshot.payload, "summary", "") or sanitize_user_message(getattr(snapshot.payload, "reason", ""))
        recorded = self.job_repo.record_result(task_id, result, message, utc_now())
        if recorded is not None:
            self._reschedule_recurring_job(recorded, consume_current=True)
        self._log_schedule_event(task_id, trigger, message or result.value)
        self._refresh_schedules()

    def _reschedule_recurring_job(self, job: ScheduledJob, *, consume_current: bool) -> None:
        updated = schedule_next_run(job, consume_current=consume_current)
        updated = ScheduledJob(
            task_id=updated.task_id,
            instruction=updated.instruction,
            run_at=updated.run_at,
            recurrence=updated.recurrence,
            enabled=updated.enabled,
            last_result=updated.last_result,
            last_message=updated.last_message,
            last_run_at=updated.last_run_at,
            weekdays=updated.weekdays,
            interval_minutes=updated.interval_minutes,
            random_runs_per_day=updated.random_runs_per_day,
            next_run_at=updated.next_run_at,
            planned_run_times=updated.planned_run_times,
            created_at=updated.created_at,
            updated_at=utc_now(),
        )
        self.job_repo.upsert(updated)
        if not updated.enabled or not updated.next_run_at:
            return
        try:
            execute, arguments, working_directory = self._scheduler_command(updated.task_id)
            self.task_scheduler.register_job(updated, execute, arguments, working_directory)
        except TaskSchedulerError as exc:
            self._log_schedule_event(updated.task_id, "reschedule_failed", sanitize_user_message(str(exc)) or str(exc))

    def _log_schedule_event(self, task_id: str, event_type: str, message: str) -> None:
        append_jsonl(
            self.paths.logs_dir / "audit_log.jsonl",
            {
                "type": "schedule",
                "task_id": task_id,
                "event": event_type,
                "message": message,
                "timestamp": utc_now(),
            },
        )

    def _show_main_window(self) -> None:
        self._backgrounded_run = False
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._hide_floating_controls()

    def _open_settings_page(self) -> None:
        self._select_page("settings")
        self._show_main_window()
        self._refresh_codex_auth_silent()

    def _show_floating_controls(self) -> None:
        if self._is_session_active():
            controls = self._ensure_floating_controls()
            controls.set_goal(self.current_goal)
            controls.set_status(self.current_status, self.current_tone, self.current_activity)
            controls.set_pause_label(self.home_page.pause_button.text())
            controls.set_stop_label(self.home_page.stop_button.text())
            controls.present()

    def _move_to_background(self, notify: bool = True) -> None:
        if not self._is_session_active():
            return
        self._backgrounded_run = True
        self.hide()
        controls = self._ensure_floating_controls()
        controls.set_goal(self.current_goal)
        controls.set_status(self.current_status, self.current_tone, self.current_activity)
        controls.set_pause_label(self.home_page.pause_button.text())
        controls.set_stop_label(self.home_page.stop_button.text())
        controls.present()
        if self.tray_icon is not None and notify and not self._tray_notice_sent:
            self.tray_icon.showMessage(APP_TITLE, self._background_shortcut_message())
            self._tray_notice_sent = True

    def _change_language(self, locale: str) -> None:
        if locale not in {"en", "ja"}:
            return
        set_locale(locale)
        self.preferences["language"] = locale
        self._save_preferences()
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(APP_TITLE)
        self.sidebar_logo.setPixmap(self._load_brand_pixmap(40))
        if self.floating_controls is not None:
            self.floating_controls.set_logo_pixmap(self._load_brand_pixmap(30))
        self.sidebar_buttons["home"].setText(tr("sidebar.new_thread"))
        self.sidebar_buttons["knowledge"].setText(tr("tab.knowledge"))
        self.sidebar_buttons["schedules"].setText(tr("tab.schedules"))
        self.sidebar_buttons["threads"].setText(tr("tab.history"))
        self.sidebar_buttons["settings"].setText(tr("tab.settings"))
        self.home_page.retranslate()
        self.history_page.retranslate()
        self.knowledge_page.retranslate()
        self.schedules_page.retranslate()
        self.settings_page.retranslate()
        if self.floating_controls is not None:
            self.floating_controls.retranslate()
        if self.tray_open_action is not None:
            self.tray_open_action.setText(tr("tray.show_main"))
        if self.tray_settings_action is not None:
            self.tray_settings_action.setText(tr("tab.settings"))
        if self.tray_controls_action is not None:
            self.tray_controls_action.setText(tr("tray.show_controls"))
        if self.tray_quit_action is not None:
            self.tray_quit_action.setText(tr("tray.quit"))
        self._refresh_settings()
        self._refresh_history()
        self._refresh_schedules()
        self._refresh_knowledge()
        self.current_status = tr(self.current_status_key)
        if self.current_tone == "ready":
            self.current_activity = ""
        elif self.current_status_key:
            phase_key = self.current_status_key.replace("status.", "message.phase_")
            self.current_activity = tr(phase_key) if phase_key in {
                "message.phase_loading",
                "message.phase_observing",
                "message.phase_planning",
                "message.phase_precheck",
                "message.phase_executing",
                "message.phase_postcheck",
                "message.phase_replanning",
                "message.phase_paused",
                "message.phase_stopped",
                "message.phase_failed",
                "message.phase_completed",
            } else self._translate_known_text(
                self.current_activity,
                prefixes=("message.", "status.", "flow.", "demo."),
            )
        self.current_connection = self._translate_known_text(
            self.current_connection,
            prefixes=("message.", "value.", "status."),
        )
        self._update_connection_state()
        self._select_page(self.current_page)
        self._refresh_compact_surfaces()
        self._refresh_footer_copy()

    def _refresh_settings(self) -> None:
        self.settings_page.set_general_values(
            language=self.preferences.get("language", "en"),
            autonomy_mode=self.preferences.get("autonomy_mode", "autonomous"),
            max_steps=self.preferences.get("max_steps_per_session"),
            pause_hotkey=self.preferences.get("pause_hotkey", "F8"),
            stop_hotkey=self.preferences.get("stop_hotkey", "F12"),
            system_prompt_options=self._system_prompt_options(),
            selected_system_prompt=self._current_system_prompt_selection(),
        )
        self.settings_page.set_storage_values(
            ttl_days=int(self.preferences.get("screenshot_ttl_days", 3)),
            keep_days=int(self.preferences.get("keep_important_screenshots_days", 14)),
            history_limit=int(self.preferences.get("history_display_limit", 120)),
        )
        self._refresh_codex_panel(force_live=self.current_page == "settings")

    def _update_connection_state(self) -> None:
        signed_in = read_cached_auth_mode() == "chatgpt"
        key = translation_key_for_text(self.current_connection, prefixes=("message.", "value.", "status."))
        if not signed_in:
            self.current_connection = tr("message.codex_sign_in_required")
        elif key == "message.codex_sign_in_required":
            self.current_connection = ""
        elif self.current_connection:
            self.current_connection = self._translate_known_text(
                self.current_connection,
                prefixes=("message.", "value.", "status."),
            )
        self.home_page.connection_hint.setText(self.current_connection)
        self.home_page.connection_hint.setVisible(bool(self.current_connection))

    def _status_tone(self, state: SessionState) -> str:
        if state in {SessionState.FAILED, SessionState.STOPPED}:
            return "error"
        if state == SessionState.PAUSED:
            return "paused"
        if state == SessionState.COMPLETED:
            return "done"
        if state in {
            SessionState.EXECUTING,
            SessionState.PLANNING,
            SessionState.OBSERVING,
            SessionState.PRECHECK,
            SessionState.POSTCHECK,
            SessionState.REPLANNING,
            SessionState.LOADING_CONTEXT,
        }:
            return "running"
        return "ready"

    def _start_session(self, instruction: str) -> None:
        if self._is_session_active():
            self._show_notice(tr("message.already_running"), tone="warning")
            return
        if not instruction:
            self._show_notice(tr("message.need_instruction"), tone="warning")
            return
        blocked_message = self._default_run_block_message()
        if blocked_message:
            self._set_status(tr("status.failed"), "error", blocked_message, blocked_message)
            self.home_page.set_running(False)
            self._show_main_window()
            self._show_notice(blocked_message, tone="error", timeout_ms=8000)
            return
        self._start_session_internal(instruction, task_id="", trigger="manual", move_to_background=True)

    def _toggle_pause(self) -> None:
        if not self._is_session_active():
            return
        if self.current_status_key == "status.paused":
            self.orchestrator.resume()
        else:
            self.orchestrator.pause()
        self._update_pause_controls()

    def _stop_session(self) -> None:
        if self._is_session_active():
            self.orchestrator.stop()
            self.codex_app_server.cancel_active_turn()
            self._set_status(tr("status.stopped"), "error", tr("message.phase_stopped"), self.current_connection)
            self._update_pause_controls()

    def _pump_events(self) -> None:
        while not self.event_queue.empty():
            kind, payload = self.event_queue.get_nowait()
            if kind == "command":
                if payload.get("command") == "run_task":
                    self._enqueue_scheduled_task(payload.get("task_id", ""))
                elif payload.get("command") == "show_main":
                    self._show_main_window()
            elif kind == "state":
                snapshot = payload["snapshot"]
                self._set_status(
                    friendly_state(snapshot.state.value),
                    self._status_tone(snapshot.state),
                    friendly_state_hint(snapshot.state.value),
                    self.current_connection,
                )
                self._update_pause_controls()
            elif kind == "observation":
                self.home_page.set_preview(payload["observation"].screenshot_path)
            elif kind == "plan":
                self._set_activity(payload["plan"].summary)
            elif kind == "provider_notice":
                message = sanitize_user_message(payload["message"]) or payload["message"]
                self.current_connection = self._translate_known_text(
                    message,
                    prefixes=("message.", "value.", "status."),
                )
                self.home_page.connection_hint.setText(self.current_connection)
                self.home_page.connection_hint.setVisible(True)
                self._update_tray_state()
            elif kind == "finished":
                snapshot = payload["snapshot"]
                reason = (
                    getattr(snapshot.payload, "summary", "")
                    if snapshot.state == SessionState.COMPLETED
                    else sanitize_user_message(getattr(snapshot.payload, "reason", ""))
                )
                visibility_action = finish_visibility_action(
                    backgrounded=self._backgrounded_run,
                    trigger=self.active_trigger,
                    tray_available=self.tray_icon is not None,
                )
                self._set_status(
                    friendly_state(snapshot.state.value),
                    self._status_tone(snapshot.state),
                    reason or friendly_state_hint(snapshot.state.value),
                    self.current_connection,
                )
                self.home_page.set_running(False)
                self._hide_floating_controls()
                if visibility_action == "show_main":
                    self._show_main_window()
                elif visibility_action == "notify_tray" and self.tray_icon is not None:
                    self._backgrounded_run = False
                    self.tray_icon.showMessage(
                        APP_TITLE,
                        f"{friendly_state(snapshot.state.value)}: {reason or friendly_state_hint(snapshot.state.value)}",
                    )
                else:
                    self._backgrounded_run = False
                self._refresh_history()
                self._refresh_knowledge()
            elif kind == "worker_done":
                self.worker = None
                self._record_job_completion(payload["snapshot"], payload.get("task_id", ""), payload.get("trigger", "manual"))
                self.active_task_id = ""
                self.active_trigger = "manual"
                self._start_next_queued_task()
            elif kind == "worker_failed":
                self.worker = None
                message = payload.get("message", "") or tr("message.run_internal_error")
                task_id = payload.get("task_id", "")
                trigger = payload.get("trigger", "manual")
                append_jsonl(
                    self.paths.logs_dir / "audit_log.jsonl",
                    {
                        "type": "worker_error",
                        "task_id": task_id,
                        "trigger": trigger,
                        "message": message,
                        "timestamp": utc_now(),
                    },
                )
                if task_id:
                    job = self.job_repo.get(task_id)
                    ran_at = utc_now()
                    self.job_repo.record_result(task_id, ScheduledJobState.FAILED, message, ran_at)
                    if job is not None:
                        self._append_schedule_history(job, message, ran_at, "failed")
                    self._refresh_schedules()
                    self._refresh_history()
                self.active_task_id = ""
                self.active_trigger = "manual"
                self.home_page.set_running(False)
                self._hide_floating_controls()
                self._backgrounded_run = False
                self._set_status(tr("status.failed"), "error", message, self.current_connection)
                if trigger == "manual":
                    self._show_main_window()
                    self._show_notice(message, tone="error", timeout_ms=8000)
                elif self.tray_icon is not None:
                    self.tray_icon.showMessage(APP_TITLE, message)
                self._start_next_queued_task()

    def _refresh_history(self, preferred_session_id: str | None = None) -> None:
        selected_id = preferred_session_id if preferred_session_id is not None else self.selected_history_id
        self.history_records = load_session_history(self.paths, limit=int(self.preferences.get("history_display_limit", 120)))
        active_payload = None
        if self.history_records:
            target_index = 0
            if selected_id:
                for index, record in enumerate(self.history_records):
                    if record.get("session_id") == selected_id:
                        target_index = index
                        break
            active_payload = self.history_records[target_index]
        active_session_id = active_payload.get("session_id", "") if active_payload else ""
        self.history_page.set_records(self.history_records, active_session_id)
        self._show_history_payload(active_payload)

    def _refresh_schedules(self) -> None:
        self.schedule_records = load_scheduled_jobs(self.paths)
        current_task_id = self.schedules_page.current_task_id
        self.schedules_page.set_jobs(self.schedule_records)
        if current_task_id:
            for payload in self.schedule_records:
                if payload.get("task_id") == current_task_id:
                    self.schedules_page.load_job(payload)
                    break

    def _new_schedule(self) -> None:
        self._select_page("schedules")
        self.schedules_page.clear_form()

    def _save_schedule(self, payload: dict) -> None:
        instruction = payload.get("instruction", "").strip()
        if not instruction:
            self._show_notice(tr("message.schedule_missing_instruction"), tone="warning")
            return

        recurrence_value = payload.get("recurrence", "once")
        recurrence = ScheduleKind(recurrence_value)
        run_at = payload.get("run_at", "")
        if recurrence == ScheduleKind.ONCE:
            try:
                scheduled_at = run_at.replace("Z", "+00:00") if run_at.endswith("Z") else run_at
                if scheduled_at and datetime.fromisoformat(scheduled_at) <= datetime.now():
                    self._show_notice(tr("message.schedule_future_required"), tone="warning")
                    return
            except ValueError:
                self._show_notice(tr("message.schedule_future_required"), tone="warning")
                return

        existing = self.job_repo.get(payload.get("task_id", ""))
        task_id = existing.task_id if existing else (payload.get("task_id") or uuid.uuid4().hex[:10])
        weekdays = [payload.get("weekday", "Monday")] if recurrence == ScheduleKind.WEEKLY else []
        job = ScheduledJob(
            task_id=task_id,
            instruction=instruction,
            run_at=run_at,
            recurrence=recurrence,
            enabled=existing.enabled if existing else True,
            last_result=existing.last_result if existing else ScheduledJobState.SCHEDULED,
            last_message=existing.last_message if existing else "",
            last_run_at=existing.last_run_at if existing else "",
            weekdays=weekdays,
            interval_minutes=max(1, int(payload.get("interval_minutes", 0) or 0)),
            random_runs_per_day=max(1, int(payload.get("random_runs_per_day", 1) or 1)),
            next_run_at=existing.next_run_at if existing else "",
            planned_run_times=list(existing.planned_run_times) if existing else [],
            created_at=existing.created_at if existing else utc_now(),
            updated_at=utc_now(),
        )
        job = schedule_next_run(job)
        try:
            execute, arguments, working_directory = self._scheduler_command(task_id)
            self.task_scheduler.register_job(job, execute, arguments, working_directory)
        except TaskSchedulerError as exc:
            self._show_notice(
                f"{tr('message.schedule_scheduler_error')}\n{sanitize_user_message(str(exc))}",
                tone="error",
                timeout_ms=8000,
            )
            return
        self.job_repo.upsert(job)
        self._log_schedule_event(task_id, "saved", tr("message.schedule_saved"))
        self._refresh_schedules()
        self._show_notice(tr("message.schedule_saved"), tone="success")

    def _enable_schedule(self, task_id: str) -> None:
        if not task_id:
            return
        job = self.job_repo.get(task_id)
        if job is None:
            return
        try:
            updated = schedule_next_run(job)
            updated = ScheduledJob(
                task_id=updated.task_id,
                instruction=updated.instruction,
                run_at=updated.run_at,
                recurrence=updated.recurrence,
                enabled=True,
                last_result=updated.last_result,
                last_message=updated.last_message,
                last_run_at=updated.last_run_at,
                weekdays=updated.weekdays,
                interval_minutes=updated.interval_minutes,
                random_runs_per_day=updated.random_runs_per_day,
                next_run_at=updated.next_run_at,
                planned_run_times=updated.planned_run_times,
                created_at=updated.created_at,
                updated_at=utc_now(),
            )
            execute, arguments, working_directory = self._scheduler_command(task_id)
            self.task_scheduler.register_job(updated, execute, arguments, working_directory)
            self.job_repo.upsert(updated)
            self._log_schedule_event(task_id, "enabled", tr("schedule.enable"))
            self._refresh_schedules()
        except TaskSchedulerError as exc:
            self._show_notice(
                f"{tr('message.schedule_scheduler_error')}\n{sanitize_user_message(str(exc))}",
                tone="error",
                timeout_ms=8000,
            )

    def _disable_schedule(self, task_id: str) -> None:
        if not task_id:
            return
        try:
            self.task_scheduler.set_enabled(task_id, False)
            self.job_repo.set_enabled(task_id, False)
            self._log_schedule_event(task_id, "disabled", tr("schedule.disable"))
            self._refresh_schedules()
        except TaskSchedulerError as exc:
            self._show_notice(
                f"{tr('message.schedule_scheduler_error')}\n{sanitize_user_message(str(exc))}",
                tone="error",
                timeout_ms=8000,
            )

    def _delete_schedule(self, task_id: str) -> None:
        if not task_id:
            return
        try:
            self.task_scheduler.delete_job(task_id)
        except TaskSchedulerError as exc:
            self._show_notice(
                f"{tr('message.schedule_scheduler_error')}\n{sanitize_user_message(str(exc))}",
                tone="error",
                timeout_ms=8000,
            )
            return
        self.job_repo.delete(task_id)
        try:
            self.pending_task_queue.remove(task_id)
        except ValueError:
            pass
        self._log_schedule_event(task_id, "deleted", tr("message.schedule_deleted"))
        self._refresh_schedules()
        self._show_notice(tr("message.schedule_deleted"), tone="success")

    def _scheduler_command(self, task_id: str) -> tuple[str, str, str]:
        if getattr(sys, "frozen", False):
            executable = str(Path(sys.executable).resolve())
            working_directory = str(Path(executable).parent)
            arguments = f"--run-task {task_id}"
            return executable, arguments, working_directory

        main_script = self.paths.root / "main.py"
        return (
            sys.executable,
            f'"{main_script}" --run-task {task_id}',
            str(self.paths.root),
        )

    def _show_history_payload(self, payload: dict | None) -> None:
        if not payload:
            self.selected_history_id = ""
            self.history_page.clear_detail()
            return
        self.selected_history_id = payload.get("session_id", "")
        detail = load_session_detail(self.paths, self.selected_history_id)
        history = detail["history"] or dict(payload)
        result_text = history.get("display_result", "") or friendly_result(history.get("result", ""))
        app_text = history.get("display_app", "") or friendly_app_name(history.get("target_app", ""))
        summary = (
            f"{history.get('display_time', '')}  |  "
            f"{result_text}  |  "
            f"{app_text}"
        )
        lines = [
            f"{tr('label.instruction')}: {history.get('instruction', '')}",
            f"{tr('label.result')}: {result_text}",
            f"{tr('label.steps')}: {history.get('step_count', 0)}",
            f"{tr('history.flow')}:",
        ]
        flow = history.get("flow") or []
        lines.extend([f"- {friendly_flow(item)}" for item in flow] or [f"- {tr('value.none')}"])
        lines.extend(["", f"{tr('history.confirmations')}:"])
        lines.extend([f"- {note}" for note in (history.get("important_confirmations") or [])] or [f"- {tr('value.none')}"])
        lines.extend(
            [
                "",
                f"{tr('history.failure_reason')}: "
                f"{sanitize_user_message(history.get('failure_reason', '')) or tr('value.none')}",
                "",
                f"{tr('history.used_context')}:",
            ]
        )
        loaded_context = history.get("used_context") or []
        lines.extend([f"- {Path(item).name}" for item in loaded_context] or [f"- {tr('value.none')}"])
        self.history_page.show_detail(summary, "\n".join(lines), detail["captures"])

    def _delete_selected_thread(self) -> None:
        if not self.selected_history_id:
            return
        current_index = next(
            (index for index, record in enumerate(self.history_records) if record.get("session_id") == self.selected_history_id),
            -1,
        )
        next_session_id = ""
        if current_index >= 0:
            replacement_index = current_index + 1 if current_index + 1 < len(self.history_records) else current_index - 1
            if 0 <= replacement_index < len(self.history_records):
                next_session_id = self.history_records[replacement_index].get("session_id", "")
        try:
            deleted = delete_session_thread(self.paths, self.selected_history_id)
        except OSError as exc:
            self._show_notice(
                f"{tr('message.thread_delete_failed')}\n{sanitize_user_message(str(exc))}",
                tone="error",
                timeout_ms=8000,
            )
            return
        self.selected_history_id = next_session_id
        self._refresh_history(preferred_session_id=next_session_id)
        if deleted:
            self._show_notice(tr("message.thread_deleted"), tone="success")

    def _open_history_diagnostics(self) -> None:
        if not self.selected_history_id:
            return
        detail = load_session_detail(self.paths, self.selected_history_id)
        payload = {
            "history": detail["history"],
            "audit": detail["audit"],
            "execution": detail["execution"],
        }
        self._open_text_dialog(tr("window.diagnostics"), json.dumps(payload, ensure_ascii=False, indent=2))

    def _refresh_knowledge(self) -> None:
        self.knowledge_data = build_knowledge_items(self.paths)
        self.knowledge_page.set_items(self.knowledge_data)

    def _show_knowledge_payload(self, payload: dict | None) -> None:
        if not payload:
            return
        self.selected_knowledge_item = payload
        meta = (
            f"{tr('label.target')}: {payload.get('target', '')}  |  "
            f"{tr('label.kind')}: {payload.get('kind_label', '')}  |  "
            f"{tr('label.enabled')}: {payload.get('status', '')}"
        )
        self.knowledge_page.show_item(payload.get("summary", ""), meta)

    def _open_knowledge_detail(self) -> None:
        if not self.selected_knowledge_item:
            return
        detail_path = self.selected_knowledge_item.get("detail_path")
        if self.selected_knowledge_item.get("detail_path"):
            text = read_text(Path(detail_path))
        else:
            text = json.dumps(self.selected_knowledge_item.get("detail_payload", {}), ensure_ascii=False, indent=2)
        self._open_text_dialog(
            tr("window.details"),
            text,
            editable=bool(detail_path),
            save_path=Path(detail_path) if detail_path else None,
        )

    def _create_knowledge_item(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.paths.custom_prompt_dir.mkdir(parents=True, exist_ok=True)
        path = self.paths.custom_prompt_dir / f"custom_prompt_{timestamp}.md"
        title = path.stem
        body = f"# {title}\n\nAdd custom instructions here.\n"
        path.write_text(body, encoding="utf-8")
        self._refresh_knowledge()
        created = next(
            (
                item
                for items in self.knowledge_data.values()
                for item in items
                if item.get("detail_path") == str(path)
            ),
            None,
        )
        if created:
            self.selected_knowledge_item = created
            self._show_knowledge_payload(created)
        self._open_text_dialog(tr("window.details"), read_text(path), editable=True, save_path=path)

    def _default_run_block_message(self) -> str:
        if read_cached_auth_mode() != "chatgpt":
            return tr("message.codex_sign_in_required")
        try:
            self.codex_app_server.ensure_available()
        except CodexAppServerError as exc:
            return sanitize_user_message(str(exc)) or tr("message.codex_cli_missing")
        return ""

    def _refresh_model_catalog(self, *, force_live: bool) -> None:
        if self._codex_models and not force_live:
            return
        try:
            self._codex_models = self.codex_app_server.list_models()
        except CodexAppServerError:
            if force_live:
                self._codex_models = self._codex_models or []

    def _model_options(self, current_model: str) -> list[tuple[str, str]]:
        if not self._codex_models:
            normalized = current_model or "gpt-5.4"
            return [(normalized, normalized)]
        options = [
            (profile.display_name or profile.model_id, profile.model_id)
            for profile in sorted(self._codex_models, key=lambda item: (not item.is_default, item.display_name or item.model_id))
        ]
        if current_model and current_model not in {value for _, value in options}:
            options.append((current_model, current_model))
        return options

    def _effort_options(self, model: str) -> list[str]:
        for profile in self._codex_models:
            if profile.model_id == model and profile.supported_reasoning_efforts:
                return profile.supported_reasoning_efforts
        return ["low", "medium", "high", "xhigh"]

    def _effort_catalog(self) -> dict[str, list[str]]:
        return {
            profile.model_id: list(profile.supported_reasoning_efforts or ["low", "medium", "high", "xhigh"])
            for profile in self._codex_models
        }

    def _service_tier_options(self, model: str) -> list[str]:
        for profile in self._codex_models:
            if profile.model_id == model and profile.supported_service_tiers:
                return profile.supported_service_tiers
        return ["auto"]

    def _service_tier_catalog(self) -> dict[str, list[str]]:
        return {
            profile.model_id: list(profile.supported_service_tiers or ["auto"])
            for profile in self._codex_models
        }

    def _refresh_codex_panel(self, *, force_live: bool, result: str | None = None) -> None:
        setting = self.provider_repo.get_default()
        auth_status = tr("value.not_configured")
        account_text = tr("message.codex_sign_in_required")
        command_text = ""
        can_sign_in = True
        can_sign_out = False

        try:
            command_text = self.codex_app_server.ensure_available().label
            self._refresh_model_catalog(force_live=force_live)
        except CodexAppServerError as exc:
            command_text = sanitize_user_message(str(exc)) or tr("message.codex_cli_missing")
            self.settings_page.set_codex_values(
                command=command_text,
                auth_status=auth_status,
                account=account_text,
                result=result or command_text,
                can_sign_in=False,
                can_sign_out=False,
                model=setting.model,
                reasoning_effort=setting.reasoning_effort,
                service_tier=setting.service_tier,
                max_tokens=setting.max_tokens,
                model_options=self._model_options(setting.model),
                effort_options=self._effort_options(setting.model),
                effort_catalog=self._effort_catalog(),
                service_tier_options=self._service_tier_options(setting.model),
                service_tier_catalog=self._service_tier_catalog(),
            )
            return

        account: CodexAccountState | None = None
        if force_live:
            try:
                account = self.codex_app_server.read_account(refresh_token=False)
            except CodexAppServerError as exc:
                result = result or (sanitize_user_message(str(exc)) or tr("message.codex_refresh_failed"))

        if account is None:
            cached_mode = read_cached_auth_mode()
            if cached_mode == "chatgpt":
                auth_status = tr("value.chatgpt_signed_in")
                account_text = tr("message.codex_cached_session")
                can_sign_in = False
                can_sign_out = True
            elif cached_mode:
                auth_status = cached_mode
                account_text = tr("message.codex_sign_in_required")
        else:
            auth_status, account_text, can_sign_in, can_sign_out = self._format_codex_account(account)
            self._pending_login_id = ""

        self.settings_page.set_codex_values(
            command=command_text,
            auth_status=auth_status,
            account=account_text,
            result=result or self._codex_result_message,
            can_sign_in=can_sign_in,
            can_sign_out=can_sign_out,
            model=setting.model,
            reasoning_effort=setting.reasoning_effort,
            service_tier=setting.service_tier,
            max_tokens=setting.max_tokens,
            model_options=self._model_options(setting.model),
            effort_options=self._effort_options(setting.model),
            effort_catalog=self._effort_catalog(),
            service_tier_options=self._service_tier_options(setting.model),
            service_tier_catalog=self._service_tier_catalog(),
        )

    def _format_codex_account(self, account: CodexAccountState) -> tuple[str, str, bool, bool]:
        if account.auth_mode == "chatgpt":
            detail_parts = [part for part in (account.email, account.plan_type.upper()) if part]
            detail = " | ".join(detail_parts) if detail_parts else tr("value.chatgpt_managed_session")
            return tr("value.chatgpt_signed_in"), detail, False, True
        if account.auth_mode:
            return account.auth_mode, tr("message.codex_sign_in_required"), True, False
        return tr("value.not_configured"), tr("message.codex_sign_in_required"), True, False

    def _save_general_settings(self) -> None:
        payload = self.settings_page.general_payload()
        self.preferences.update(payload)
        self.pending_system_prompt_selection = None
        self._save_preferences()
        self._refresh_hotkeys(show_feedback=True)
        self._update_connection_state()
        self._refresh_settings()

    def _save_ai_settings(self) -> None:
        payload = self.settings_page.ai_payload()
        current = self.provider_repo.get_default()
        updated = type(current)(
            provider=current.provider,
            base_url=current.base_url,
            model=payload["model"] or current.model,
            reasoning_effort=payload["reasoning_effort"],
            timeout_seconds=current.timeout_seconds,
            retry_count=current.retry_count,
            max_tokens=payload["max_tokens"],
            allow_images=True,
            is_default=True,
            service_tier=payload["service_tier"],
        )
        self.provider_repo.upsert(updated)
        self._refresh_codex_panel(force_live=False)

    def _refresh_codex_auth(self) -> None:
        try:
            self._codex_result_message = ""
            self._refresh_codex_panel(force_live=True)
            self._update_connection_state()
        except Exception as exc:  # noqa: BLE001
            message = sanitize_user_message(str(exc)) or tr("message.codex_refresh_failed")
            self._codex_result_message = message
            self._refresh_codex_panel(force_live=False, result=message)
            self._show_notice(message, tone="warning", timeout_ms=8000)

    def _refresh_codex_auth_silent(self) -> None:
        try:
            self._refresh_codex_panel(force_live=True)
            self._update_connection_state()
        except Exception:  # noqa: BLE001
            return

    def _sign_in_with_chatgpt(self) -> None:
        try:
            login = self.codex_app_server.start_chatgpt_login()
            self._pending_login_id = login["login_id"]
            self._codex_result_message = tr("message.codex_browser_opened")
            QDesktopServices.openUrl(QUrl(login["auth_url"]))
            self._refresh_codex_panel(force_live=False, result=self._codex_result_message)
            self._show_notice(self._codex_result_message, timeout_ms=7000)
        except Exception as exc:  # noqa: BLE001
            message = sanitize_user_message(str(exc)) or tr("message.codex_cli_missing")
            self._codex_result_message = message
            self._refresh_codex_panel(force_live=False, result=message)
            self._show_notice(message, tone="error", timeout_ms=8000)

    def _sign_out_codex(self) -> None:
        try:
            self.codex_app_server.logout()
            self._pending_login_id = ""
            self._codex_result_message = tr("message.codex_signed_out")
            self._refresh_codex_panel(force_live=False, result=self._codex_result_message)
            self._update_connection_state()
            self._show_notice(self._codex_result_message)
        except Exception as exc:  # noqa: BLE001
            message = sanitize_user_message(str(exc)) or tr("message.codex_refresh_failed")
            self._codex_result_message = message
            self._refresh_codex_panel(force_live=False, result=message)
            self._show_notice(message, tone="warning", timeout_ms=8000)

    def _test_ai_connection(self) -> None:
        try:
            setting = self.provider_repo.get_default()
            result = self.provider_registry.get(setting.provider).test_connection(setting, "")
            message = sanitize_user_message(result.message) or result.message
            self._codex_result_message = message
            self._refresh_codex_panel(force_live=True, result=message)
            append_jsonl(
                self.paths.logs_dir / "audit_log.jsonl",
                {"type": "provider_test", "provider": setting.provider, "ok": result.ok, "message": message},
            )
        except ProviderError as exc:
            message = sanitize_user_message(exc.user_message) or exc.user_message
            self._codex_result_message = message
            self._refresh_codex_panel(force_live=False, result=message)
            append_jsonl(
                self.paths.logs_dir / "audit_log.jsonl",
                {"type": "provider_test", "provider": "unknown", "ok": False, "message": message},
            )
        except Exception as exc:  # noqa: BLE001
            message = sanitize_user_message(str(exc)) or tr("message.provider")
            self._codex_result_message = message
            self._refresh_codex_panel(force_live=False, result=message)
            append_jsonl(
                self.paths.logs_dir / "audit_log.jsonl",
                {"type": "provider_test", "provider": "unknown", "ok": False, "message": message},
            )

    def _save_storage_settings(self) -> None:
        payload = self.settings_page.storage_payload()
        self.preferences.update(payload)
        self._save_preferences()
        self._refresh_history()

    def _purge_screenshots(self) -> None:
        payload = self.settings_page.storage_payload()
        deleted = self.orchestrator.retention.purge(
            default_ttl_days=payload["screenshot_ttl_days"],
            important_ttl_days=payload["keep_important_screenshots_days"],
        )
        self._show_notice(tr("message.screenshots_purged", count=deleted), tone="success")

    def _system_prompt_options(self) -> list[str]:
        return self.paths.iter_systemprompt_names()

    def _current_system_prompt_selection(self) -> str:
        if self.pending_system_prompt_selection is not None:
            return self.pending_system_prompt_selection
        return str(self.preferences.get("selected_system_prompt", "") or "").strip()

    def _selected_system_prompt_path(self) -> Path | None:
        selected = self._current_system_prompt_selection()
        if not selected:
            return None
        return self.paths.resolve_systemprompt_path(selected)

    def _remember_system_prompt_selection(self, selected: str) -> None:
        normalized = str(selected or "").strip()
        if self.preferences.get("selected_system_prompt", "") == normalized:
            self.pending_system_prompt_selection = None
            return
        self.pending_system_prompt_selection = normalized

    def _new_system_prompt(self) -> None:
        path = self.paths.systemprompt_dir / f"systemprompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        write_text_file(path, "# System Prompt\n\nDescribe the execution style for this profile.\n", encoding="utf-8")
        self.preferences["selected_system_prompt"] = path.name
        self.pending_system_prompt_selection = None
        self._save_preferences()
        self._refresh_settings()
        self._open_text_dialog(path.stem, read_text(path), editable=True, save_path=path)

    def _edit_system_prompt(self) -> None:
        path = self._selected_system_prompt_path()
        if path is None:
            self._new_system_prompt()
            return
        save_path = path
        if path.parent != self.paths.systemprompt_dir:
            save_path = self.paths.systemprompt_dir / path.name
            if not save_path.exists():
                write_text_file(save_path, read_text(path), encoding="utf-8")
            self.preferences["selected_system_prompt"] = save_path.name
            self.pending_system_prompt_selection = None
            self._save_preferences()
            self._refresh_settings()
        self._open_text_dialog(save_path.stem, read_text(save_path), editable=True, save_path=save_path)

    def _open_system_prompt_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.systemprompt_dir)))

    def _open_screenshots_folder(self) -> None:
        self.paths.screenshots_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.screenshots_dir)))

    def _create_live_planner(self) -> LiveActionPlanner | None:
        return LiveActionPlanner(
            provider_repo=self.provider_repo,
            secret_store=self.secret_store,
            provider_registry=self.provider_registry,
            notice_callback=lambda message: self.event_queue.put(("provider_notice", {"message": message})),
        )

    def _create_toolset(self):
        live_planner = self._create_live_planner()
        mode = self.preferences.get("default_adapter_mode", AdapterMode.WINDOWS.value)
        if mode == AdapterMode.MOCK.value:
            return MockAgentToolset(
                root=self.paths.root,
                live_planner=live_planner,
            )
        window_manager = WindowManager()
        uia_adapter = UIAAdapter()
        browser_sensor = BrowserSensorHub()
        automation_router = AutomationRouter([uia_adapter, PlaywrightAdapter(browser_sensor.page())])
        return WindowsAgentToolset(
            root=self.paths.root,
            observation_builder=WindowsObservationBuilder(
                screenshot_provider=ScreenshotProvider(),
                window_manager=window_manager,
                uia_adapter=uia_adapter,
                browser_sensor=browser_sensor,
                automation_router=automation_router,
            ),
            window_manager=window_manager,
            input_executor=InputExecutor(window_manager),
            uia_adapter=uia_adapter,
            live_planner=live_planner,
            automation_router=automation_router,
            browser_sensor=browser_sensor,
        )

    def _open_text_dialog(
        self,
        title: str,
        text: str,
        *,
        editable: bool = False,
        save_path: Path | None = None,
    ) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(980, 720)
        dialog.setStyleSheet(f"QDialog {{ background: {COLORS.background}; }}")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        viewer = AppTextEditor()
        viewer.setPlainText(text)
        viewer.setReadOnly(not editable)
        layout.addWidget(viewer)
        actions = QHBoxLayout()
        actions.addStretch(1)
        if editable and save_path is not None:
            save_button = AppButton(tr("button.save"), "primary")

            def save_current_text() -> None:
                try:
                    write_text_file(save_path, viewer.toPlainText(), encoding="utf-8")
                    self._refresh_knowledge()
                    if save_path.parent == self.paths.systemprompt_dir:
                        self.preferences["selected_system_prompt"] = save_path.name
                        self.pending_system_prompt_selection = None
                        self._save_preferences()
                        self._refresh_settings()
                    updated = next(
                        (
                            item
                            for items in self.knowledge_data.values()
                            for item in items
                            if item.get("detail_path") == str(save_path)
                        ),
                        self.selected_knowledge_item,
                    )
                    if updated:
                        self._show_knowledge_payload(updated)
                except OSError as exc:
                    QMessageBox.warning(self, APP_TITLE, sanitize_user_message(str(exc)) or str(exc))

            save_button.clicked.connect(save_current_text)
            actions.addWidget(save_button)
        close_button = AppButton(tr("button.close"), "ghost")
        close_button.clicked.connect(dialog.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        dialog.exec()

    def _quit_application(self) -> None:
        self._shutdown_runtime()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _wait_for_worker_shutdown(self, timeout_seconds: float = 3.0) -> None:
        worker = self.worker
        if worker is None:
            return
        worker.join(timeout=max(timeout_seconds, 0.0))
        if not worker.is_alive():
            self.worker = None

    def _shutdown_runtime(self) -> None:
        if self._is_session_active():
            self.orchestrator.stop()
            self.codex_app_server.cancel_active_turn()
            self._wait_for_worker_shutdown()
        self._hide_floating_controls()
        self.hotkey_manager.close()
        app = QApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self.hotkey_manager)
        self.command_server.close()
        self.codex_app_server.close()
        if self.tray_icon is not None:
            self.tray_icon.hide()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized() and self._is_session_active():
            QTimer.singleShot(0, lambda: self._move_to_background(notify=False))
        elif event.type() == QEvent.ActivationChange and self.isActiveWindow() and self.current_page == "settings":
            QTimer.singleShot(0, self._refresh_codex_auth_silent)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._shutdown_runtime()
        super().closeEvent(event)

    def load_demo_state(self) -> None:
        self.home_page.goal_input.setPlainText(tr("demo.goal"))
        self._set_goal(tr("demo.goal"))
        self._set_status(
            friendly_state(SessionState.EXECUTING.value),
            "running",
            tr("demo.status_hint"),
            tr("message.connection_ready"),
        )
        self._set_activity(tr("demo.next_action"))
        self._refresh_history()
        if not self.history_records:
            self.history_records = [
                {
                    "session_id": "demo-1",
                    "instruction": tr("demo.goal"),
                    "display_time": "2026-04-01 09:42",
                    "display_app": "Excel",
                    "display_result": friendly_result("success"),
                    "step_count": 4,
                },
                {
                    "session_id": "demo-2",
                    "instruction": tr("demo.secondary_goal"),
                    "display_time": "2026-03-31 18:10",
                    "display_app": friendly_app_name("windows_settings"),
                    "display_result": friendly_result("stopped"),
                    "step_count": 2,
                },
            ]

        if self.history_records:
            self._show_history_payload(self.history_records[0])
        self._select_page("home")


def launch_ui(
    workspace_root: Path,
    data_root: Path | None = None,
    pending_task_id: str = "",
    start_hidden: bool = False,
) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow(workspace_root, data_root=data_root, pending_task_id=pending_task_id, start_hidden=start_hidden)
    if not start_hidden:
        window.show()
    app.exec()
