from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from autocruise.infrastructure.codex_models import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_MODEL_LABEL,
    DEFAULT_CODEX_REASONING_EFFORT,
    DEFAULT_CODEX_REASONING_EFFORTS,
    DEFAULT_CODEX_SERVICE_TIER,
    DEFAULT_CODEX_SERVICE_TIERS,
)
from autocruise.infrastructure.windows.global_hotkeys import HOTKEY_OPTIONS
from autocruise.presentation.labels import tr
from autocruise.presentation.ui.components import AppButton, AppComboBox, AppLineEdit, Card, SectionHeader, ThinScrollBar


class SettingsPage(QWidget):
    save_general_requested = Signal()
    save_ai_requested = Signal()
    sign_in_requested = Signal()
    sign_out_requested = Signal()
    test_ai_requested = Signal()
    save_storage_requested = Signal()
    purge_requested = Signal()
    new_system_prompt_requested = Signal()
    edit_system_prompt_requested = Signal()
    open_system_prompt_folder_requested = Signal()
    open_screenshots_requested = Signal()
    language_changed = Signal(str)
    system_prompt_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model_effort_options: dict[str, list[str]] = {}
        self._model_service_tier_options: dict[str, list[str]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBar(ThinScrollBar(Qt.Vertical, scroll))
        scroll.setViewportMargins(0, 0, 12, 0)
        scroll.verticalScrollBar().setSingleStep(20)
        layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(24)

        self.general_card = Card()
        general_layout = QGridLayout(self.general_card)
        general_layout.setContentsMargins(24, 24, 24, 24)
        general_layout.setHorizontalSpacing(16)
        general_layout.setVerticalSpacing(12)
        self.general_header = SectionHeader(tr("label.general"), tr("settings.general_subtitle"))
        general_layout.addWidget(self.general_header, 0, 0, 1, 2)

        self.language_label = QLabel(tr("label.language"))
        self.language_label.setProperty("role", "body")
        general_layout.addWidget(self.language_label, 1, 0)
        self.language_combo = AppComboBox()
        self._populate_language_combo()
        general_layout.addWidget(self.language_combo, 1, 1)

        self.autonomy_label = QLabel(tr("label.autonomy"))
        self.autonomy_label.setProperty("role", "body")
        general_layout.addWidget(self.autonomy_label, 2, 0)
        self.autonomy_combo = AppComboBox()
        self._populate_autonomy_combo()
        general_layout.addWidget(self.autonomy_combo, 2, 1)

        self.pause_hotkey_label = QLabel(tr("label.pause_hotkey"))
        self.pause_hotkey_label.setProperty("role", "body")
        general_layout.addWidget(self.pause_hotkey_label, 3, 0)
        self.pause_hotkey_combo = AppComboBox()
        self._populate_hotkey_combo(self.pause_hotkey_combo)
        general_layout.addWidget(self.pause_hotkey_combo, 3, 1)

        self.stop_hotkey_label = QLabel(tr("label.stop_hotkey"))
        self.stop_hotkey_label.setProperty("role", "body")
        general_layout.addWidget(self.stop_hotkey_label, 4, 0)
        self.stop_hotkey_combo = AppComboBox()
        self._populate_hotkey_combo(self.stop_hotkey_combo)
        general_layout.addWidget(self.stop_hotkey_combo, 4, 1)

        self.system_prompt_label = QLabel(tr("label.system_prompt"))
        self.system_prompt_label.setProperty("role", "body")
        general_layout.addWidget(self.system_prompt_label, 5, 0)
        self.system_prompt_combo = AppComboBox()
        general_layout.addWidget(self.system_prompt_combo, 5, 1)
        self.system_prompt_actions = QHBoxLayout()
        self.system_prompt_actions.setContentsMargins(0, 0, 0, 0)
        self.system_prompt_actions.setSpacing(8)
        self.general_save = AppButton(tr("button.save"), "primary")
        self.system_prompt_new = AppButton(tr("button.new"), "secondary")
        self.system_prompt_edit = AppButton(tr("button.edit"), "secondary")
        self.system_prompt_open_folder = AppButton(tr("button.open_folder"), "ghost")
        self.system_prompt_actions.addWidget(self.general_save)
        self.system_prompt_actions.addWidget(self.system_prompt_new)
        self.system_prompt_actions.addWidget(self.system_prompt_edit)
        self.system_prompt_actions.addWidget(self.system_prompt_open_folder)
        self.system_prompt_actions.addStretch(1)
        general_layout.addLayout(self.system_prompt_actions, 6, 0, 1, 2)
        content_layout.addWidget(self.general_card)

        self.ai_card = Card()
        ai_layout = QGridLayout(self.ai_card)
        ai_layout.setContentsMargins(24, 24, 24, 24)
        ai_layout.setHorizontalSpacing(16)
        ai_layout.setVerticalSpacing(12)
        self.ai_header = SectionHeader(tr("label.ai_connection"), tr("settings.ai_subtitle"))
        ai_layout.addWidget(self.ai_header, 0, 0, 1, 2)

        self.provider_label = QLabel(tr("label.provider"))
        self.provider_label.setProperty("role", "body")
        self.provider_value = QLabel("Codex App Server")
        self.provider_value.setProperty("role", "body")

        self.command_label = QLabel(tr("label.codex_runtime"))
        self.command_label.setProperty("role", "body")
        self.command_value = QLabel("")
        self.command_value.setWordWrap(True)
        self.command_value.setProperty("role", "muted")

        self.auth_label = QLabel(tr("label.codex_auth_status"))
        self.auth_label.setProperty("role", "body")
        self.auth_value = QLabel("")
        self.auth_value.setWordWrap(True)
        self.auth_value.setProperty("role", "body")

        self.account_label = QLabel(tr("label.codex_account"))
        self.account_label.setProperty("role", "body")
        self.account_value = QLabel("")
        self.account_value.setWordWrap(True)
        self.account_value.setProperty("role", "muted")

        self.model_label = QLabel(tr("label.model"))
        self.model_label.setProperty("role", "body")
        self.model_combo = AppComboBox()
        self.model_combo.setEditable(False)
        self.model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.model_combo.addItem(DEFAULT_CODEX_MODEL_LABEL, DEFAULT_CODEX_MODEL)
        self.model_combo.setEnabled(False)

        self.effort_label = QLabel(tr("label.reasoning_effort"))
        self.effort_label.setProperty("role", "body")
        self.effort_combo = AppComboBox()
        self._populate_effort_combo()

        self.service_tier_label = QLabel(tr("label.service_tier"))
        self.service_tier_label.setProperty("role", "body")
        self.service_tier_combo = AppComboBox()
        self._populate_service_tier_combo()
        self.service_tier_panel = QWidget()
        self.service_tier_panel.setAttribute(Qt.WA_StyledBackground, False)
        self.service_tier_panel.setStyleSheet("background: transparent;")
        self.service_tier_panel_layout = QVBoxLayout(self.service_tier_panel)
        self.service_tier_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.service_tier_panel_layout.setSpacing(0)
        self.service_tier_panel_layout.addWidget(self.service_tier_combo)

        self.response_size_label = QLabel(tr("label.response_size"))
        self.response_size_label.setProperty("role", "body")
        self.response_size_combo = AppComboBox()
        self._populate_response_size_combo()
        self.response_size_panel = QWidget()
        self.response_size_panel.setAttribute(Qt.WA_StyledBackground, False)
        self.response_size_panel.setStyleSheet("background: transparent;")
        self.response_size_panel_layout = QVBoxLayout(self.response_size_panel)
        self.response_size_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.response_size_panel_layout.setSpacing(0)
        self.response_size_panel_layout.addWidget(self.response_size_combo)

        for row, (label, widget) in enumerate(
            (
                (self.provider_label, self.provider_value),
                (self.command_label, self.command_value),
                (self.auth_label, self.auth_value),
                (self.account_label, self.account_value),
                (self.model_label, self.model_combo),
                (self.effort_label, self.effort_combo),
                (self.service_tier_label, self.service_tier_panel),
                (self.response_size_label, self.response_size_panel),
            ),
            start=1,
        ):
            ai_layout.addWidget(label, row, 0)
            ai_layout.addWidget(widget, row, 1)

        self.ai_result = QLabel("")
        self.ai_result.setProperty("role", "body")
        self.ai_result.setWordWrap(True)
        ai_layout.addWidget(self.ai_result, 9, 0, 1, 2)

        self.sign_in_button = AppButton(tr("button.sign_in"), "primary")
        self.sign_out_button = AppButton(tr("button.sign_out"), "ghost")
        self.ai_save = AppButton(tr("button.save"), "primary")
        self.ai_actions = QHBoxLayout()
        self.ai_actions.setContentsMargins(0, 0, 0, 0)
        self.ai_actions.setSpacing(8)
        self.ai_actions.addWidget(self.ai_save)
        self.ai_actions.addWidget(self.sign_out_button)
        self.ai_actions.addWidget(self.sign_in_button)
        self.ai_actions.addStretch(1)
        ai_layout.addLayout(self.ai_actions, 10, 0, 1, 2)
        content_layout.addWidget(self.ai_card)

        self.storage_card = Card()
        storage_layout = QGridLayout(self.storage_card)
        storage_layout.setContentsMargins(24, 24, 24, 24)
        storage_layout.setHorizontalSpacing(16)
        storage_layout.setVerticalSpacing(12)
        self.storage_header = SectionHeader(tr("label.storage"), tr("settings.storage_subtitle"))
        storage_layout.addWidget(self.storage_header, 0, 0, 1, 2)
        self.ttl_label = QLabel(tr("label.screenshot_ttl"))
        self.ttl_label.setProperty("role", "body")
        self.ttl_edit = AppLineEdit()
        self.keep_label = QLabel(tr("label.keep_important_screenshots"))
        self.keep_label.setProperty("role", "body")
        self.keep_edit = AppLineEdit()
        self.limit_label = QLabel(tr("label.history_limit"))
        self.limit_label.setProperty("role", "body")
        self.limit_edit = AppLineEdit()
        for row, (label, widget) in enumerate(
            (
                (self.ttl_label, self.ttl_edit),
                (self.keep_label, self.keep_edit),
                (self.limit_label, self.limit_edit),
            ),
            start=1,
        ):
            storage_layout.addWidget(label, row, 0)
            storage_layout.addWidget(widget, row, 1)
        self.storage_save = AppButton(tr("button.save"), "primary")
        self.purge_button = AppButton(tr("button.cleanup"), "secondary")
        self.open_screenshots_button = AppButton(tr("button.open_screenshots"), "secondary")
        self.storage_actions = QHBoxLayout()
        self.storage_actions.setContentsMargins(0, 0, 0, 0)
        self.storage_actions.setSpacing(8)
        self.storage_actions.addWidget(self.storage_save)
        self.storage_actions.addWidget(self.open_screenshots_button)
        self.storage_actions.addWidget(self.purge_button)
        self.storage_actions.addStretch(1)
        storage_layout.addLayout(self.storage_actions, 4, 0, 1, 2)
        content_layout.addWidget(self.storage_card)
        content_layout.addStretch(1)

        self.general_save.clicked.connect(self.save_general_requested.emit)
        self.ai_save.clicked.connect(self.save_ai_requested.emit)
        self.sign_in_button.clicked.connect(self.sign_in_requested.emit)
        self.sign_out_button.clicked.connect(self.sign_out_requested.emit)
        self.storage_save.clicked.connect(self.save_storage_requested.emit)
        self.purge_button.clicked.connect(self.purge_requested.emit)
        self.system_prompt_new.clicked.connect(self.new_system_prompt_requested.emit)
        self.system_prompt_edit.clicked.connect(self.edit_system_prompt_requested.emit)
        self.system_prompt_open_folder.clicked.connect(self.open_system_prompt_folder_requested.emit)
        self.open_screenshots_button.clicked.connect(self.open_screenshots_requested.emit)
        self.language_combo.currentIndexChanged.connect(self._emit_language)
        self.model_combo.currentTextChanged.connect(self._sync_model_dependent_options)
        self.system_prompt_combo.currentIndexChanged.connect(
            self._emit_system_prompt_change
        )

    def _populate_language_combo(self) -> None:
        current = self.language_combo.currentData()
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        self.language_combo.addItem(tr("language.english"), "en")
        self.language_combo.addItem(tr("language.japanese"), "ja")
        self.language_combo.setCurrentIndex(self._find_index(self.language_combo, current or "en"))
        self.language_combo.blockSignals(False)

    def _populate_autonomy_combo(self) -> None:
        current = self.autonomy_combo.currentData()
        self.autonomy_combo.clear()
        self.autonomy_combo.addItem(tr("value.autonomy_autonomous"), "autonomous")
        self.autonomy_combo.addItem(tr("value.autonomy_balanced"), "balanced")
        self.autonomy_combo.setCurrentIndex(self._find_index(self.autonomy_combo, current or "autonomous"))

    def _populate_hotkey_combo(self, combo: AppComboBox) -> None:
        current = combo.currentData()
        combo.clear()
        for value, label in HOTKEY_OPTIONS:
            text = tr("value.shortcut_disabled") if not value else label
            combo.addItem(text, value)
        combo.setCurrentIndex(self._find_index(combo, current or ""))

    def _populate_effort_combo(self, options: list[str] | None = None) -> None:
        current = self.effort_combo.currentData()
        self.effort_combo.clear()
        efforts = options or DEFAULT_CODEX_REASONING_EFFORTS
        for effort in efforts:
            self.effort_combo.addItem(self._label_for_effort(effort), effort)
        self.effort_combo.setCurrentIndex(self._find_index(self.effort_combo, current or DEFAULT_CODEX_REASONING_EFFORT))

    def _populate_service_tier_combo(self, options: list[str] | None = None) -> None:
        current = self.service_tier_combo.currentData()
        self.service_tier_combo.clear()
        tiers = options or DEFAULT_CODEX_SERVICE_TIERS
        for tier in tiers:
            self.service_tier_combo.addItem(self._label_for_service_tier(tier), tier)
        self.service_tier_combo.setCurrentIndex(self._find_index(self.service_tier_combo, current or DEFAULT_CODEX_SERVICE_TIER))

    def _populate_response_size_combo(self) -> None:
        current = self.response_size_combo.currentData()
        self.response_size_combo.clear()
        for value, label_key in (
            (1024, "value.response_size_compact"),
            (2048, "value.response_size_standard"),
            (3072, "value.response_size_detailed"),
            (4096, "value.response_size_max"),
        ):
            self.response_size_combo.addItem(tr(label_key), value)
        target = current if current is not None else 2048
        index = self._find_index(self.response_size_combo, target)
        self.response_size_combo.setCurrentIndex(index)

    def _find_index(self, combo: AppComboBox, value) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                return index
        return 0

    def _find_text_index(self, combo: AppComboBox, value: str) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == value or combo.itemText(index) == value:
                return index
        return -1

    def _emit_language(self) -> None:
        self.language_changed.emit(self.language_combo.currentData() or "en")

    def _emit_system_prompt_change(self) -> None:
        selected = self.system_prompt_combo.currentData() or ""
        self.system_prompt_edit.setEnabled(bool(selected))
        self.system_prompt_changed.emit(selected)

    def _label_for_effort(self, effort: str) -> str:
        key = f"value.effort_{(effort or '').strip().lower()}"
        translated = tr(key)
        return translated if translated != key else (effort or "").strip().upper()

    def _label_for_service_tier(self, tier: str) -> str:
        key = f"value.service_tier_{(tier or '').strip().lower()}"
        translated = tr(key)
        if translated != key:
            return translated
        normalized = (tier or "").strip()
        return normalized[:1].upper() + normalized[1:] if normalized else "Standard"

    def _sync_model_dependent_options(self) -> None:
        model = DEFAULT_CODEX_MODEL
        effort = self.effort_combo.currentData() or DEFAULT_CODEX_REASONING_EFFORT
        service_tier = self.service_tier_combo.currentData() or DEFAULT_CODEX_SERVICE_TIER
        self._populate_effort_combo(self._available_effort_options(model))
        self.effort_combo.setCurrentIndex(self._find_index(self.effort_combo, effort))
        self._populate_service_tier_combo(self._available_service_tier_options(model))
        self.service_tier_combo.setCurrentIndex(self._find_index(self.service_tier_combo, service_tier))
        self.service_tier_combo.setEnabled(self.service_tier_combo.count() > 1)

    def _available_effort_options(self, model: str) -> list[str]:
        return self._model_effort_options.get(model, DEFAULT_CODEX_REASONING_EFFORTS)

    def _available_service_tier_options(self, model: str) -> list[str]:
        return self._model_service_tier_options.get(model, DEFAULT_CODEX_SERVICE_TIERS)

    def set_general_values(
        self,
        language: str,
        autonomy_mode: str,
        max_steps: int | None,
        pause_hotkey: str,
        stop_hotkey: str,
        system_prompt_options: list[str] | None = None,
        selected_system_prompt: str = "",
    ) -> None:
        self.language_combo.setCurrentIndex(self._find_index(self.language_combo, language))
        self.autonomy_combo.setCurrentIndex(self._find_index(self.autonomy_combo, autonomy_mode))
        self.pause_hotkey_combo.setCurrentIndex(self._find_index(self.pause_hotkey_combo, pause_hotkey))
        self.stop_hotkey_combo.setCurrentIndex(self._find_index(self.stop_hotkey_combo, stop_hotkey))
        self.system_prompt_combo.blockSignals(True)
        self.system_prompt_combo.clear()
        self.system_prompt_combo.addItem(tr("value.none"), "")
        for option in system_prompt_options or []:
            self.system_prompt_combo.addItem(option, option)
        self.system_prompt_combo.setCurrentIndex(self._find_index(self.system_prompt_combo, selected_system_prompt))
        self.system_prompt_combo.blockSignals(False)
        self.system_prompt_edit.setEnabled(bool(self.system_prompt_combo.currentData()))

    def set_codex_values(
        self,
        *,
        command: str,
        auth_status: str,
        account: str,
        result: str,
        can_sign_in: bool,
        can_sign_out: bool,
        model: str,
        reasoning_effort: str,
        service_tier: str,
        max_tokens: int,
        model_options: list[tuple[str, str]] | None = None,
        effort_options: list[str] | None = None,
        effort_catalog: dict[str, list[str]] | None = None,
        service_tier_options: list[str] | None = None,
        service_tier_catalog: dict[str, list[str]] | None = None,
    ) -> None:
        self.command_value.setText(command)
        self.auth_value.setText(auth_status)
        self.account_value.setText(account)
        self.ai_result.setText(result)
        _ = model, model_options
        self._model_effort_options = {DEFAULT_CODEX_MODEL: DEFAULT_CODEX_REASONING_EFFORTS}
        self._model_service_tier_options = {DEFAULT_CODEX_MODEL: DEFAULT_CODEX_SERVICE_TIERS}
        if effort_catalog and DEFAULT_CODEX_MODEL in effort_catalog:
            self._model_effort_options[DEFAULT_CODEX_MODEL] = list(effort_catalog[DEFAULT_CODEX_MODEL])
        if service_tier_catalog and DEFAULT_CODEX_MODEL in service_tier_catalog:
            self._model_service_tier_options[DEFAULT_CODEX_MODEL] = list(service_tier_catalog[DEFAULT_CODEX_MODEL])
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem(DEFAULT_CODEX_MODEL_LABEL, DEFAULT_CODEX_MODEL)
        self.model_combo.setCurrentIndex(0)
        self.model_combo.setEnabled(False)
        self.model_combo.blockSignals(False)
        if effort_options is not None:
            self._model_effort_options[DEFAULT_CODEX_MODEL] = list(effort_options)
        if service_tier_options is not None:
            self._model_service_tier_options[DEFAULT_CODEX_MODEL] = list(service_tier_options)
        self._sync_model_dependent_options()
        self.effort_combo.setCurrentIndex(self._find_index(self.effort_combo, reasoning_effort or DEFAULT_CODEX_REASONING_EFFORT))
        self.service_tier_combo.setCurrentIndex(self._find_index(self.service_tier_combo, service_tier or DEFAULT_CODEX_SERVICE_TIER))
        self._populate_response_size_combo()
        token_index = self._find_index(self.response_size_combo, max_tokens)
        if token_index == 0 and self.response_size_combo.itemData(0) != max_tokens:
            self.response_size_combo.addItem(tr("value.response_size_custom", value=max_tokens), max_tokens)
            token_index = self.response_size_combo.count() - 1
        self.response_size_combo.setCurrentIndex(token_index)
        self.sign_in_button.setEnabled(can_sign_in)
        self.sign_out_button.setEnabled(can_sign_out)

    def set_storage_values(self, ttl_days: int, keep_days: int, history_limit: int) -> None:
        self.ttl_edit.setText(str(ttl_days))
        self.keep_edit.setText(str(keep_days))
        self.limit_edit.setText(str(history_limit))

    def general_payload(self) -> dict:
        return {
            "language": self.language_combo.currentData() or "en",
            "autonomy_mode": self.autonomy_combo.currentData() or "autonomous",
            "max_steps_limit_enabled": False,
            "max_steps_per_session": None,
            "pause_hotkey": self.pause_hotkey_combo.currentData() or "",
            "stop_hotkey": self.stop_hotkey_combo.currentData() or "",
            "selected_system_prompt": self.system_prompt_combo.currentData() or "",
        }

    def ai_payload(self) -> dict:
        return {
            "model": DEFAULT_CODEX_MODEL,
            "reasoning_effort": self.effort_combo.currentData() or DEFAULT_CODEX_REASONING_EFFORT,
            "service_tier": self.service_tier_combo.currentData() or DEFAULT_CODEX_SERVICE_TIER,
            "max_tokens": int(self.response_size_combo.currentData() or 2048),
        }

    def storage_payload(self) -> dict:
        return {
            "screenshot_ttl_days": self._safe_int(self.ttl_edit.text(), 3, 1, 365),
            "keep_important_screenshots_days": self._safe_int(self.keep_edit.text(), 14, 1, 3650),
            "history_display_limit": self._safe_int(self.limit_edit.text(), 120, 20, 500),
        }

    def _safe_int(self, value: str, fallback: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value or str(fallback))
        except ValueError:
            parsed = fallback
        return max(minimum, min(maximum, parsed))

    def retranslate(self) -> None:
        selected_language = self.language_combo.currentData() or "en"
        selected_autonomy = self.autonomy_combo.currentData() or "autonomous"
        selected_pause_hotkey = self.pause_hotkey_combo.currentData() or ""
        selected_stop_hotkey = self.stop_hotkey_combo.currentData() or ""
        selected_effort = self.effort_combo.currentData() or DEFAULT_CODEX_REASONING_EFFORT
        selected_service_tier = self.service_tier_combo.currentData() or DEFAULT_CODEX_SERVICE_TIER
        selected_model = DEFAULT_CODEX_MODEL
        self._populate_language_combo()
        self.language_combo.setCurrentIndex(self._find_index(self.language_combo, selected_language))
        self._populate_autonomy_combo()
        self.autonomy_combo.setCurrentIndex(self._find_index(self.autonomy_combo, selected_autonomy))
        self._populate_hotkey_combo(self.pause_hotkey_combo)
        self.pause_hotkey_combo.setCurrentIndex(self._find_index(self.pause_hotkey_combo, selected_pause_hotkey))
        self._populate_hotkey_combo(self.stop_hotkey_combo)
        self.stop_hotkey_combo.setCurrentIndex(self._find_index(self.stop_hotkey_combo, selected_stop_hotkey))
        self._sync_model_dependent_options()
        self.effort_combo.setCurrentIndex(self._find_index(self.effort_combo, selected_effort))
        self.service_tier_combo.setCurrentIndex(self._find_index(self.service_tier_combo, selected_service_tier))
        self._populate_response_size_combo()
        index = self._find_text_index(self.model_combo, selected_model)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self.general_header.set_text(tr("label.general"), tr("settings.general_subtitle"))
        self.language_label.setText(tr("label.language"))
        self.autonomy_label.setText(tr("label.autonomy"))
        self.pause_hotkey_label.setText(tr("label.pause_hotkey"))
        self.stop_hotkey_label.setText(tr("label.stop_hotkey"))
        self.system_prompt_label.setText(tr("label.system_prompt"))
        self.system_prompt_new.setText(tr("button.new"))
        self.system_prompt_edit.setText(tr("button.edit"))
        self.system_prompt_open_folder.setText(tr("button.open_folder"))
        self.general_save.setText(tr("button.save"))
        self.ai_header.set_text(tr("label.ai_connection"), tr("settings.ai_subtitle"))
        self.provider_label.setText(tr("label.provider"))
        self.command_label.setText(tr("label.codex_runtime"))
        self.auth_label.setText(tr("label.codex_auth_status"))
        self.account_label.setText(tr("label.codex_account"))
        self.model_label.setText(tr("label.model"))
        self.effort_label.setText(tr("label.reasoning_effort"))
        self.service_tier_label.setText(tr("label.service_tier"))
        self.response_size_label.setText(tr("label.response_size"))
        self.sign_in_button.setText(tr("button.sign_in"))
        self.sign_out_button.setText(tr("button.sign_out"))
        self.ai_save.setText(tr("button.save"))
        self.storage_header.set_text(tr("label.storage"), tr("settings.storage_subtitle"))
        self.ttl_label.setText(tr("label.screenshot_ttl"))
        self.keep_label.setText(tr("label.keep_important_screenshots"))
        self.limit_label.setText(tr("label.history_limit"))
        self.storage_save.setText(tr("button.save"))
        self.purge_button.setText(tr("button.cleanup"))
        self.open_screenshots_button.setText(tr("button.open_screenshots"))
