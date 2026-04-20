from __future__ import annotations

import json
import os
import shutil
import threading
import sys
import tempfile
import time
import unittest
import ctypes
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
QT_APP = QApplication.instance() or QApplication([])

from autocruise.application.live_planner import LiveActionPlanner
from autocruise.application.orchestrator import SessionOrchestrator
from autocruise.application.retrieval import RetrievalPlanner
from autocruise.application.state_machine import InvalidStateTransition, SessionStateMachine
from autocruise.domain.automation import AutomationBackend, AutomationElementState, AutomationOperation
from autocruise.domain.models import (
    Action,
    ActionType,
    AdapterMode,
    Bounds,
    DetectedElement,
    ExpectedSignal,
    ExpectedSignalKind,
    ExecutionResult,
    ExecutingData,
    LoadingContextData,
    Observation,
    ObservationKind,
    ObservingData,
    PlanningData,
    PlanStep,
    PostcheckData,
    PrecheckData,
    ReplanningData,
    PointerPoint,
    PointerStroke,
    PrimarySensorSnapshot,
    RetrievedContext,
    ScheduleKind,
    ScheduledJob,
    ScheduledJobState,
    SessionMission,
    SessionState,
    TargetRef,
    WindowInfo,
    utc_now,
)
from autocruise.infrastructure.ipc import LocalCommandServer, send_command
from autocruise.infrastructure.mock import MockAgentToolset
from autocruise.infrastructure.automation import AutomationRouter
from autocruise.infrastructure.browser.playwright_adapter import PlaywrightAdapter
from autocruise.infrastructure.browser.sensor import BrowserSensorHub
from autocruise.infrastructure import codex_app_server as codex_app_server_module
from autocruise.infrastructure.windows import uia_client as uia_client_module
from autocruise.infrastructure.providers import CodexProviderClient, ProviderClient, ProviderError, ProviderRegistry
from autocruise.infrastructure.storage import (
    ProviderSettingsRepository,
    ScheduledJobRepository,
    ScreenshotRetentionService,
    WorkspacePaths,
    append_jsonl,
    load_structured,
    read_jsonl,
)
from autocruise.infrastructure.windows.global_hotkeys import GlobalHotkeyManager, hotkey_to_native, normalize_hotkey
from autocruise.infrastructure.windows.input_executor import INPUT, KEYBDINPUT, InputExecutor, VK_LWIN, VK_RETURN, user32 as input_user32
from autocruise.infrastructure.windows.observation_builder import WindowsObservationBuilder
from autocruise.infrastructure.windows.primary_sensor import match_expected_signals
from autocruise.infrastructure.windows.screenshot_provider import ScreenshotProvider, gdi32, user32 as screenshot_user32
from autocruise.infrastructure.windows.shell_executor import ShellExecutor
from autocruise.infrastructure.windows.uia_adapter import UIAAdapter
from autocruise.infrastructure.windows.uia_client import UiaClientLayer
from autocruise.infrastructure.windows.visual_guidance import annotate_image, build_visual_guide_state
from autocruise.infrastructure.windows.window_manager import user32 as window_user32
from autocruise.infrastructure.windows.toolset import WindowsAgentToolset
from autocruise.presentation.data_sources import (
    build_knowledge_items,
    delete_session_thread,
    load_scheduled_jobs,
    load_session_detail,
)
from autocruise.presentation.labels import (
    friendly_state_hint,
    sanitize_user_message,
    set_locale,
    tr,
    translation_key_for_text,
)
from autocruise.presentation.ui.components import AppLineEdit, AppTextEditor
from autocruise.presentation.ui.pages.home_page import HomePage
from autocruise.presentation.ui.pages.history_page import HistoryPage
from autocruise.presentation.ui.pages.settings_page import SettingsPage
from autocruise.presentation.ui.theme import build_stylesheet
from autocruise.presentation.ui.shell import (
    FloatingControlWidget,
    build_product_footer,
    button_text_with_shortcut,
    compact_panel_copy,
    finish_visibility_action,
    normalize_preferences,
    notice_label_style,
)


def bootstrap_workspace(root: Path) -> WorkspacePaths:
    (root / "constitution").mkdir(parents=True, exist_ok=True)
    (root / "users" / "default").mkdir(parents=True, exist_ok=True)

    (root / "constitution" / "constitution.md").write_text("# Test Constitution", encoding="utf-8")
    (root / "users" / "default" / "user_custom_prompt.md").write_text("# User Prompt", encoding="utf-8")
    (root / "users" / "default" / "preferences.yaml").write_text(
        json.dumps(
            {
                "screenshot_ttl_days": 3,
                "keep_important_screenshots_days": 14,
                "default_adapter_mode": "mock",
                "autonomy_mode": "autonomous",
                "pause_hotkey": "F8",
                "stop_hotkey": "F12",
            }
        ),
        encoding="utf-8",
    )

    paths = WorkspacePaths(root)
    paths.ensure()
    return paths


class FakeProviderClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text

    def generate_text(self, settings, api_key, instructions, prompt, image_path=None, session_key=None, output_schema=None):
        return self.response_text


class FakeProviderRegistry:
    def __init__(self, response_text: str) -> None:
        self.client = FakeProviderClient(response_text)

    def get(self, provider: str):
        return self.client


class FakeProviderRepo:
    def __init__(self, settings) -> None:
        self.settings = settings

    def get_default(self):
        return self.settings


class FakeSecretStore:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def load_api_key(self, provider: str) -> str:
        return self.api_key


class RecordingProviderClient(ProviderClient):
    def __init__(self, response_text: str | list[str] = "OK") -> None:
        if isinstance(response_text, list):
            self.responses = list(response_text)
        else:
            self.responses = [response_text]
        self.image_path = ""
        self.session_key = ""
        self.output_schema = None
        self.prompt = ""
        self.instructions = ""
        self.calls = 0

    def generate_text(self, settings, api_key, instructions, prompt, image_path=None, session_key=None, output_schema=None):
        self.calls += 1
        self.instructions = instructions
        self.prompt = prompt
        self.image_path = image_path or ""
        self.session_key = session_key or ""
        self.output_schema = output_schema
        index = min(self.calls - 1, len(self.responses) - 1)
        return self.responses[index]


class DummyObservationBuilder:
    def capture(self, screenshot_path, recent_actions):
        raise NotImplementedError


class RecordingObservationBuilder(DummyObservationBuilder):
    def __init__(self, observation: Observation) -> None:
        self.observation = observation
        self.full_calls = 0
        self.reuse_calls = 0
        self.structured_calls = 0
        self.vision_calls = 0

    def capture_full(self, screenshot_path, recent_actions, previous_observation=None, sensor_snapshot=None):
        self.full_calls += 1
        observation = self.observation
        observation.raw_ref = {
            **dict(observation.raw_ref or {}),
            "sensor_snapshot": asdict(sensor_snapshot) if sensor_snapshot is not None else {},
            "observation_kind": ObservationKind.FULL.value,
            "vision_fallback_required": False,
        }
        observation.screenshot_path = str(screenshot_path)
        return observation

    def refresh_structured(self, recent_actions, previous_observation=None, sensor_snapshot=None):
        self.structured_calls += 1
        return Observation(
            screenshot_path=None,
            active_window=self.observation.active_window,
            visible_windows=self.observation.visible_windows,
            detected_elements=self.observation.detected_elements,
            ui_tree_summary=self.observation.ui_tree_summary,
            cursor_position=self.observation.cursor_position,
            focused_element=self.observation.focused_element,
            textual_hints=self.observation.textual_hints,
            recent_actions=recent_actions,
            raw_ref={
                "sensor_snapshot": asdict(sensor_snapshot) if sensor_snapshot is not None else {},
                "observation_kind": ObservationKind.STRUCTURED.value,
                "vision_fallback_required": False,
            },
        )

    def reuse(self, previous_observation, sensor_snapshot=None, reason="sensor_unchanged"):
        self.reuse_calls += 1
        return Observation(
            screenshot_path=previous_observation.screenshot_path,
            active_window=previous_observation.active_window,
            visible_windows=previous_observation.visible_windows,
            detected_elements=previous_observation.detected_elements,
            ui_tree_summary=previous_observation.ui_tree_summary,
            cursor_position=previous_observation.cursor_position,
            focused_element=previous_observation.focused_element,
            textual_hints=previous_observation.textual_hints,
            recent_actions=previous_observation.recent_actions,
            raw_ref={
                **dict(previous_observation.raw_ref or {}),
                "sensor_snapshot": asdict(sensor_snapshot) if sensor_snapshot is not None else {},
                "observation_kind": ObservationKind.REUSED.value,
                "planner_skip_reason": reason,
                "vision_fallback_required": False,
            },
        )

    def capture_vision_fallback(
        self,
        screenshot_path,
        recent_actions,
        previous_observation=None,
        sensor_snapshot=None,
        target_bounds=None,
    ):
        _ = target_bounds
        self.vision_calls += 1
        return Observation(
            screenshot_path=str(screenshot_path),
            active_window=self.observation.active_window,
            visible_windows=self.observation.visible_windows,
            detected_elements=self.observation.detected_elements,
            ui_tree_summary=self.observation.ui_tree_summary,
            cursor_position=self.observation.cursor_position,
            focused_element=self.observation.focused_element,
            textual_hints=self.observation.textual_hints,
            recent_actions=recent_actions,
            raw_ref={
                "sensor_snapshot": asdict(sensor_snapshot) if sensor_snapshot is not None else {},
                "observation_kind": ObservationKind.VISION_FALLBACK.value,
                "vision_fallback_required": True,
            },
        )


class StaticPrimarySensorHub:
    def __init__(self, snapshots: list[PrimarySensorSnapshot], wait_result: dict | None = None) -> None:
        self.snapshots = list(snapshots)
        self.wait_result = wait_result or {}
        self.snapshot_calls = 0

    def snapshot(self):
        index = min(self.snapshot_calls, len(self.snapshots) - 1)
        self.snapshot_calls += 1
        return self.snapshots[index]

    def wait_for_expected_signals(self, previous_snapshot, expected_signals, timeout_ms, poll_interval_ms=80):
        _ = previous_snapshot, expected_signals, timeout_ms, poll_interval_ms
        if self.wait_result:
            return self.wait_result
        return {"matched": False, "snapshot": self.snapshot(), "matched_signal": "", "wait_satisfied_by": ""}


class CountingLivePlanner:
    def __init__(self) -> None:
        self.calls = 0

    def plan(self, goal, observation, recent_actions, context):
        self.calls += 1
        return None


class DummyWindowManager:
    def list_windows(self):
        return []

    def focus_window(self, window_id: int) -> bool:
        return True

    def find_window(self, title: str):
        return WindowInfo(window_id=1, title=title)


class DummyInputExecutor:
    def execute(self, action):
        return True, "ok"


class RaisingInputExecutor:
    def execute(self, action):
        raise RuntimeError("boom")


class DummyShellExecutor:
    def __init__(self, result: ExecutionResult | None = None) -> None:
        self.result = result or ExecutionResult(success=True, details="shell ok")
        self.actions: list[Action] = []

    def execute(self, action: Action) -> ExecutionResult:
        self.actions.append(action)
        return self.result


class DummyUIAAdapter:
    def find_elements(self, query: str, limit: int = 40):
        return []

    def get_focused_element(self):
        return None


class QueryAwareUIAAdapter:
    def __init__(self, mapping: dict[str, list[DetectedElement]]) -> None:
        self.mapping = mapping

    def find_elements(self, query: str, limit: int = 40):
        return list(self.mapping.get(query, []))[:limit]

    def get_focused_element(self):
        return None


class StaticScreenshotProvider:
    def __init__(self, source: Path) -> None:
        self.source = source

    def capture(self, screenshot_path: Path, guide_state=None) -> None:
        shutil.copyfile(self.source, screenshot_path)


class StaticWindowManager:
    def __init__(self, active_window: WindowInfo, visible_windows: list[WindowInfo]) -> None:
        self.active_window = active_window
        self.visible_windows = visible_windows

    def get_active_window(self):
        return self.active_window

    def list_windows(self):
        return self.visible_windows

    def cursor_position(self):
        return (320, 240)


class FocusAwareUIAAdapter:
    def __init__(self, elements: list[DetectedElement], focused_element: DetectedElement | None) -> None:
        self.elements = elements
        self.focused_element = focused_element

    def find_elements(self, query: str, limit: int = 40):
        return list(self.elements)[:limit]

    def get_focused_element(self):
        return self.focused_element

    def get_automation_elements(self, query: str = "", limit: int = 40):
        return []


class FakeUiaClient(UiaClientLayer):
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.backend = AutomationBackend.UIA
        self.clicked = False
        self.typed_text = ""

    def _run(self, operation: str, **kwargs):
        return self.payloads.get(operation)


class FakeLocator:
    def __init__(self, *, click_raises: bool = False, role: str = "button") -> None:
        self.click_raises = click_raises
        self.role = role
        self.clicked = False
        self.filled = ""

    def first(self):
        return self

    def count(self):
        return 1

    def bounding_box(self):
        return {"x": 10, "y": 20, "width": 120, "height": 40}

    def get_attribute(self, name: str):
        values = {"role": self.role, "aria-label": "Submit", "id": "submit", "class": "primary"}
        return values.get(name, "")

    def inner_text(self, timeout: int = 0):
        return "Submit"

    def is_enabled(self):
        return True

    def click(self):
        if self.click_raises:
            raise RuntimeError("click failed")
        self.clicked = True

    def fill(self, text: str):
        self.filled = text

    def scroll_into_view_if_needed(self):
        return None


class FakePlaywrightPage:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.locator_obj = FakeLocator()

    def get_by_role(self, role: str, **kwargs):
        self.calls.append(f"role:{role}")
        return self.locator_obj

    def get_by_label(self, query):
        self.calls.append("label")
        return self.locator_obj

    def get_by_text(self, query):
        self.calls.append("text")
        return self.locator_obj

    def get_by_placeholder(self, query):
        self.calls.append("placeholder")
        return self.locator_obj

    def get_by_alt_text(self, query):
        self.calls.append("alt_text")
        return self.locator_obj

    def get_by_title(self, query):
        self.calls.append("title")
        return self.locator_obj


class FakeCdp:
    def __init__(self) -> None:
        self.clicked_at: tuple[int, int] | None = None

    def click_xy(self, x: int, y: int):
        self.clicked_at = (x, y)
        return type(
            "Result",
            (),
            {
                "success": True,
                "details": "clicked with cdp",
                "backend": AutomationBackend.CDP,
                "used_operation": AutomationOperation.CLICK,
            },
        )()


class AutoCruiseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="autocruise-test-"))
        self.paths = bootstrap_workspace(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_state_machine_rejects_invalid_transition(self) -> None:
        machine = SessionStateMachine()
        snapshot = machine.create("s1", SessionMission("test"))
        snapshot = machine.transition(
            snapshot,
            SessionState.LOADING_CONTEXT,
            LoadingContextData(goal="test", stage="initial"),
            "start",
        )
        with self.assertRaises(InvalidStateTransition):
            machine.transition(
                snapshot,
                SessionState.EXECUTING,
                ExecutingData(action_summary="bad"),
                "invalid",
            )

    def test_state_machine_allows_postcheck_observation_reuse_to_planning(self) -> None:
        machine = SessionStateMachine()
        snapshot = machine.create("s1", SessionMission("test"))
        snapshot = machine.transition(
            snapshot,
            SessionState.LOADING_CONTEXT,
            LoadingContextData(goal="test", stage="initial"),
            "start",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.OBSERVING,
            ObservingData(reason="observe"),
            "observe",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.PLANNING,
            PlanningData(goal="test"),
            "plan",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.PRECHECK,
            PrecheckData(action_summary="precheck"),
            "precheck",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.EXECUTING,
            ExecutingData(action_summary="execute"),
            "execute",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.POSTCHECK,
            PostcheckData(action_summary="postcheck"),
            "postcheck",
        )
        snapshot = machine.transition(snapshot, SessionState.OBSERVING, ObservingData(reason="reuse"), "reuse")
        snapshot = machine.transition(
            snapshot,
            SessionState.PLANNING,
            PlanningData(goal="test"),
            "reuse observation and plan again",
        )
        self.assertEqual(snapshot.state, SessionState.PLANNING)

    def test_retrieval_uses_only_prompt_sources(self) -> None:
        planner = RetrievalPlanner(self.temp_dir)
        context = planner.retrieve("Clean this Excel spreadsheet", stage="initial")
        paths = [Path(selection.path).name for selection in context.selections]
        kinds = [selection.kind for selection in context.selections]
        self.assertIn("constitution.md", paths)
        self.assertIn("user_custom_prompt.md", paths)
        self.assertIn("constitution", kinds)
        self.assertIn("user", kinds)
        self.assertEqual(context.app_candidates, [])
        self.assertEqual(context.task_candidates, [])

    def test_retrieval_matches_new_sales_and_technical_templates(self) -> None:
        planner = RetrievalPlanner(ROOT)

        sales_context = planner.retrieve("Outlook縺ｧ蜿嶺ｿ｡繝医Ξ繧､繧呈紛逅・＠縺ｦ縲・㍾隕√↑鬘ｧ螳｢繝｡繝ｼ繝ｫ縺ｯ荳区嶌縺阪∪縺ｧ菴懊▲縺ｦ", stage="initial")
        self.assertEqual(sales_context.app_candidates, [])
        self.assertEqual(sales_context.task_candidates, [])

        technical_context = planner.retrieve(
            "Visual Studio Code縺ｧ讀懃ｴ｢鄂ｮ謠帙・蛟呵｣懊ｒ遒ｺ隱阪＠縺ｦ縺九ｉ縲￣owerShell縺ｧgit status繧定ｦ九※繝・せ繝医ｒ螳溯｡後＠縺ｦ",
            stage="initial",
        )
        self.assertEqual(technical_context.app_candidates, [])
        self.assertEqual(technical_context.task_candidates, [])

    def test_retrieval_matches_paint_launch_and_drawing_templates(self) -> None:
        planner = RetrievalPlanner(ROOT)
        context = planner.retrieve("Open Paint and draw a simple cat line art.", stage="initial")
        self.assertEqual(context.app_candidates, [])
        self.assertEqual(context.task_candidates, [])
        constitution = next(selection for selection in context.selections if Path(selection.path).name == "constitution.md")
        self.assertNotIn("螳牙・", constitution.excerpt)
        self.assertNotIn("approval", constitution.excerpt.lower())

    def test_retrieval_matches_notepad_writing_templates(self) -> None:
        planner = RetrievalPlanner(ROOT)
        context = planner.retrieve("Open Notepad and write a paragraph.", stage="initial")
        self.assertEqual(context.app_candidates, [])
        self.assertEqual(context.task_candidates, [])

    def test_workspace_paths_systemprompt_resolution_prefers_updated_bundled_prompt(self) -> None:
        data_root = self.temp_dir / "runtime-data"
        paths = WorkspacePaths(self.temp_dir, data_root=data_root)
        paths.ensure()
        bundled = self.temp_dir / "users" / "default" / "systemprompt" / "AutoCruise.md"
        runtime = data_root / "users" / "default" / "systemprompt" / "AutoCruise.md"
        runtime.write_text("old runtime copy", encoding="utf-8")
        time.sleep(0.02)
        bundled.write_text("new bundled copy", encoding="utf-8")
        self.assertEqual(paths.resolve_systemprompt_path("AutoCruise.md"), bundled)

    def test_workspace_paths_systemprompt_options_merge_runtime_and_bundled(self) -> None:
        data_root = self.temp_dir / "runtime-data"
        paths = WorkspacePaths(self.temp_dir, data_root=data_root)
        paths.ensure()
        (self.temp_dir / "users" / "default" / "systemprompt" / "bundled-only.md").write_text(
            "# bundled",
            encoding="utf-8",
        )
        (data_root / "users" / "default" / "systemprompt" / "runtime-only.md").write_text(
            "# runtime",
            encoding="utf-8",
        )
        names = paths.iter_systemprompt_names()
        self.assertIn("bundled-only.md", names)
        self.assertIn("runtime-only.md", names)

    def test_workspace_paths_resolve_systemprompt_tolerates_non_utf8_runtime_copy(self) -> None:
        data_root = self.temp_dir / "runtime-data"
        paths = WorkspacePaths(self.temp_dir, data_root=data_root)
        paths.ensure()
        bundled = self.temp_dir / "users" / "default" / "systemprompt" / "AutoCruise.md"
        runtime = data_root / "users" / "default" / "systemprompt" / "AutoCruise.md"
        runtime.write_bytes("譌･譛ｬ隱槭・螳溯｡梧欠遉ｺ".encode("cp932"))
        time.sleep(0.02)
        bundled.write_text("bundled utf-8 copy", encoding="utf-8")
        resolved = paths.resolve_systemprompt_path("AutoCruise.md")
        self.assertEqual(resolved, bundled)

    def test_retrieval_uses_selected_bundled_systemprompt_when_runtime_copy_is_stale(self) -> None:
        data_root = self.temp_dir / "runtime-data"
        paths = WorkspacePaths(self.temp_dir, data_root=data_root)
        paths.ensure()
        bundled = self.temp_dir / "users" / "default" / "systemprompt" / "AutoCruise.md"
        runtime = data_root / "users" / "default" / "systemprompt" / "AutoCruise.md"
        runtime.write_text("stale runtime copy", encoding="utf-8")
        time.sleep(0.02)
        bundled.write_text("bundled source of truth", encoding="utf-8")
        preferences = load_structured(paths.preferences_path())
        preferences["selected_system_prompt"] = "AutoCruise.md"
        paths.preferences_path().write_text(json.dumps(preferences), encoding="utf-8")
        context = RetrievalPlanner(paths).retrieve("Run a desktop task", stage="initial")
        selection = next(item for item in context.selections if item.kind == "systemprompt")
        self.assertEqual(Path(selection.path), bundled)
        self.assertIn("bundled source of truth", selection.excerpt)

    def test_retrieval_uses_default_systemprompt_when_preference_key_is_missing(self) -> None:
        data_root = self.temp_dir / "runtime-data"
        paths = WorkspacePaths(self.temp_dir, data_root=data_root)
        paths.ensure()
        bundled = self.temp_dir / "users" / "default" / "systemprompt" / "AutoCruise.md"
        bundled.write_text("default execution prompt", encoding="utf-8")
        preferences = load_structured(paths.preferences_path())
        preferences.pop("selected_system_prompt", None)
        paths.preferences_path().write_text(json.dumps(preferences), encoding="utf-8")

        context = RetrievalPlanner(paths).retrieve("Run a desktop task", stage="initial")

        selection = next(item for item in context.selections if item.kind == "systemprompt")
        self.assertEqual(Path(selection.path), bundled)
        self.assertIn("default execution prompt", selection.excerpt)

    def test_knowledge_items_only_include_custom_prompts(self) -> None:
        items = build_knowledge_items(WorkspacePaths(ROOT))
        self.assertEqual(sorted(items.keys()), ["custom_prompt"])
        self.assertTrue(items["custom_prompt"])
        self.assertTrue(all(item["kind"] == "user" for item in items["custom_prompt"]))


    def test_mock_orchestrator_runs_end_to_end(self) -> None:
        orchestrator = SessionOrchestrator(
            self.paths,
            toolset_factory=lambda: MockAgentToolset(
                root=self.temp_dir,
            ),
        )
        result = orchestrator.run("Clean this Excel spreadsheet")
        self.assertEqual(result.state, SessionState.COMPLETED)
        self.assertGreater(len(read_jsonl(self.paths.logs_dir / "execution_log.jsonl")), 0)
        self.assertGreater(len(read_jsonl(self.paths.logs_dir / "audit_log.jsonl")), 0)
        self.assertGreater(len(read_jsonl(self.paths.logs_dir / "session_history.jsonl")), 0)

    def test_load_structured_tolerates_invalid_json(self) -> None:
        path = self.paths.preferences_path()
        path.write_text("{invalid", encoding="utf-8")
        self.assertEqual(load_structured(path), {})

    def test_read_jsonl_skips_invalid_lines(self) -> None:
        path = self.paths.logs_dir / "audit_log.jsonl"
        path.write_text('{"ok": 1}\nnot-json\n{"ok": 2}\n', encoding="utf-8")
        self.assertEqual(read_jsonl(path), [{"ok": 1}, {"ok": 2}])

    def test_screenshot_retention_purges_old_files_using_current_time(self) -> None:
        service = ScreenshotRetentionService(self.paths)
        session_dir = self.paths.session_screenshot_dir("retention-test")
        old_shot = session_dir / "old.png"
        old_shot.write_bytes(b"demo")
        very_old = 1_600_000_000
        os.utime(old_shot, (very_old, very_old))
        deleted = service.purge(default_ttl_days=1, important_ttl_days=7)
        self.assertEqual(deleted, 1)
        self.assertFalse(old_shot.exists())

    def test_local_command_server_accepts_show_main_command(self) -> None:
        received: list[dict] = []
        event = threading.Event()

        def on_message(payload: dict) -> None:
            received.append(payload)
            event.set()

        server = LocalCommandServer(self.temp_dir, on_message)
        self.assertTrue(server.start())
        try:
            self.assertTrue(send_command(self.temp_dir, {"command": "show_main"}))
            self.assertTrue(event.wait(2.0))
            self.assertEqual(received[0]["command"], "show_main")
        finally:
            server.close()

    def test_orchestrator_returns_failed_snapshot_when_toolset_creation_raises(self) -> None:
        orchestrator = SessionOrchestrator(
            self.paths,
            toolset_factory=lambda: (_ for _ in ()).throw(RuntimeError("toolset init failed")),
        )
        result = orchestrator.run("Open Notepad")
        self.assertEqual(result.state, SessionState.FAILED)
        self.assertIn("toolset init failed", getattr(result.payload, "reason", ""))

    def test_orchestrator_stop_before_execute_prevents_late_action(self) -> None:
        orchestrator: SessionOrchestrator | None = None

        class StopBeforeExecuteToolset:
            def __init__(self) -> None:
                self.execute_calls = 0
                self.observation = Observation(
                    screenshot_path=None,
                    active_window=WindowInfo(window_id=1, title="繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ", class_name="Notepad"),
                    visible_windows=[WindowInfo(window_id=1, title="繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ", class_name="Notepad")],
                    detected_elements=[],
                    ui_tree_summary="Notepad window",
                    cursor_position=(0, 0),
                    focused_element="ControlType.Document",
                    textual_hints=["繝｡繝｢蟶ｳ"],
                    recent_actions=[],
                )

            def capture_observation(self, session_id, **kwargs):
                return self.observation

            def list_windows(self):
                return []

            def focus_window(self, window_id: int) -> bool:
                return True

            def find_elements(self, query: str):
                return []

            def plan_next_action(self, goal: str, observation, recent_actions, context=None) -> PlanStep:
                return PlanStep(
                    summary="Type into Notepad",
                    action=Action(
                        type=ActionType.TYPE_TEXT,
                        target=TargetRef(window_title="繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ", control_type="ControlType.Document"),
                        purpose="Type text",
                        reason="Editor is visible",
                        preconditions=[],
                        expected_outcome="Text appears",
                        text="縺薙ｓ縺ｫ縺｡縺ｯ",
                    ),
                )

            def verify_target(self, action: Action, observation):
                assert orchestrator is not None
                orchestrator.stop()
                return type("Verification", (), {"matched": True, "confidence": 1.0, "reason": ""})()

            def execute_action(self, action: Action):
                self.execute_calls += 1
                return ExecutionResult(success=True, details="typed", error="")

            def wait_for_expected_change(self, session_id: str, action: Action, previous_observation, **kwargs):
                return self.observation

            def validate_outcome(self, expected_outcome: str, observation, previous_observation=None, action: Action | None = None):
                return type("Validation", (), {"success": True, "confidence": 1.0, "details": expected_outcome})()

            def abort_session(self, reason: str) -> None:
                return None

        toolset = StopBeforeExecuteToolset()
        orchestrator = SessionOrchestrator(self.paths, toolset_factory=lambda: toolset)
        result = orchestrator.run("Open Notepad and write a paragraph.")

        self.assertEqual(result.state, SessionState.STOPPED)
        self.assertEqual(toolset.execute_calls, 0)

    def test_orchestrator_replanning_reuses_observation_without_invalid_transition(self) -> None:
        machine = SessionStateMachine()
        snapshot = machine.create("s1", SessionMission("Open Notepad and write a sentence."))
        snapshot = machine.transition(
            snapshot,
            SessionState.LOADING_CONTEXT,
            LoadingContextData(goal="Open Notepad and write a sentence.", stage="initial"),
            "load",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.OBSERVING,
            ObservingData(reason="observe"),
            "observe",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.PLANNING,
            PlanningData(goal="Open Notepad and write a sentence."),
            "plan",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.REPLANNING,
            ReplanningData(failure_reason="Repeated action without progress", attempt=1),
            "replan",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.OBSERVING,
            ObservingData(reason="Reuse current observation for replanning"),
            "reuse observation",
        )
        snapshot = machine.transition(
            snapshot,
            SessionState.PLANNING,
            PlanningData(goal="Open Notepad and write a sentence."),
            "plan again",
        )

        self.assertEqual(snapshot.state, SessionState.PLANNING)

    def test_live_planner_parses_codex_response_without_api_key(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=FakeProviderRegistry(
                json.dumps(
                    {
                        "summary": "Click the Start button.",
                        "is_complete": False,
                        "action": {
                            "type": "click",
                            "target": {
                                "window_title": "Demo",
                                "name": "Start",
                                "control_type": "button",
                                "bounds": {"left": 10, "top": 20, "width": 30, "height": 40},
                            },
                            "purpose": "Open the task.",
                            "reason": "The target button is visible.",
                            "preconditions": ["The Start button is visible."],
                            "expected_outcome": "The task starts.",
                            "risk_level": "low",
                            "confidence": 0.8,
                            "text": "",
                            "hotkey": "",
                            "scroll_amount": 0,
                        },
                    },
                    ensure_ascii=False,
                )
            ),
        )
        observation = Observation(
            screenshot_path="demo.ppm",
            active_window=WindowInfo(window_id=1, title="Demo"),
            visible_windows=[WindowInfo(window_id=1, title="Demo")],
            detected_elements=[],
            ui_tree_summary="Demo",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=[],
            recent_actions=[],
        )
        plan = planner.plan("Start the task", observation, [], {"step_count": 1, "remaining_steps": 20, "session_id": "demo-session"})
        self.assertIsInstance(plan, PlanStep)
        self.assertEqual(plan.summary, "Click the Start button.")
        self.assertEqual(plan.action.type, ActionType.CLICK)
        self.assertEqual(plan.action.target.name, "Start")

    def test_live_planner_parses_drag_action(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=FakeProviderRegistry(
                json.dumps(
                    {
                        "summary": "Draw the first stroke on the canvas.",
                        "is_complete": False,
                        "action": {
                            "type": "drag",
                            "target": {
                                "window_title": "GIMP",
                                "name": "Canvas",
                                "control_type": "pane",
                                "bounds": {"left": 100, "top": 100, "width": 300, "height": 200},
                            },
                            "purpose": "Draw a curved line for the cat outline.",
                            "reason": "The canvas is visible and ready for one brush stroke.",
                            "preconditions": ["The brush tool is active."],
                            "expected_outcome": "A visible stroke appears on the canvas.",
                            "risk_level": "low",
                            "confidence": 0.81,
                            "drag_path": [{"x": 220, "y": 180}, {"x": 260, "y": 210}, {"x": 300, "y": 180}],
                            "drag_duration_ms": 900,
                        },
                    },
                    ensure_ascii=False,
                )
            ),
        )
        observation = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="GIMP"),
            visible_windows=[WindowInfo(window_id=1, title="GIMP")],
            detected_elements=[],
            ui_tree_summary="GIMP canvas visible",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=[],
            recent_actions=[],
        )
        plan = planner.plan("Draw a cat in GIMP", observation, [], {"session_id": "drag-demo"})
        self.assertIsInstance(plan, PlanStep)
        self.assertEqual(plan.action.type, ActionType.DRAG)
        self.assertEqual(plan.action.drag_duration_ms, 900)
        self.assertEqual(plan.action.drag_path, [PointerPoint(220, 180), PointerPoint(260, 210), PointerPoint(300, 180)])

    def test_live_planner_parses_relative_drag_action_with_outline(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=FakeProviderRegistry(
                json.dumps(
                    {
                        "summary": "Draw the head outline.",
                        "reasoning": "Paint is open, so the next step is the first curved stroke.",
                        "plan_outline": ["Launch complete", "Draw head outline", "Add ears", "Add whiskers"],
                        "is_complete": False,
                        "action": {
                            "type": "drag",
                            "target": {
                                "window_title": "Paint",
                                "name": "Canvas",
                                "control_type": "pane",
                                "bounds": {"left": 100, "top": 120, "width": 600, "height": 400},
                            },
                            "purpose": "Draw a curved head outline.",
                            "reason": "The canvas is visible and ready.",
                            "preconditions": ["Paint canvas is active."],
                            "expected_outcome": "A rounded cat head outline appears.",
                            "risk_level": "low",
                            "confidence": 0.87,
                            "drag_coordinate_mode": "relative",
                            "drag_path": [
                                {"x": 340, "y": 260},
                                {"x": 280, "y": 220},
                                {"x": 240, "y": 300},
                                {"x": 300, "y": 380},
                                {"x": 420, "y": 400},
                                {"x": 520, "y": 330},
                                {"x": 500, "y": 240},
                                {"x": 400, "y": 210}
                            ],
                            "drag_duration_ms": 1400,
                        },
                    },
                    ensure_ascii=False,
                )
            ),
        )
        observation = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="Paint"),
            visible_windows=[WindowInfo(window_id=1, title="Paint")],
            detected_elements=[],
            ui_tree_summary="Paint canvas visible",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=[],
            recent_actions=[],
        )
        plan = planner.plan("Draw a cat line art in Paint.", observation, [], {"session_id": "paint-demo"})
        self.assertEqual(plan.action.type, ActionType.DRAG)
        self.assertEqual(plan.action.drag_coordinate_mode, "relative")
        self.assertEqual(plan.plan_outline[:2], ["Launch complete", "Draw head outline"])
        self.assertEqual(len(plan.action.drag_path), 8)

    def test_live_planner_parses_pointer_script_for_multi_stroke_drawing(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=FakeProviderRegistry(
                json.dumps(
                    {
                        "summary": "Draw the cat outline with planned strokes.",
                        "reasoning": "The canvas is ready, so execute the prepared stroke plan.",
                        "plan_outline": ["Tool selected", "Draw head", "Draw body", "Pause"],
                        "is_complete": False,
                        "action": {
                            "type": "drag",
                            "target": {
                                "window_title": "Paint",
                                "name": "Canvas",
                                "control_type": "pane",
                                "bounds": {"left": 100, "top": 120, "width": 600, "height": 400},
                            },
                            "purpose": "Draw the line art with multiple strokes.",
                            "reason": "The brush is selected and the canvas is visible.",
                            "preconditions": ["Paint canvas is active."],
                            "expected_outcome": "The cat outline appears on the canvas.",
                            "risk_level": "low",
                            "confidence": 0.88,
                            "pointer_script": [
                                {
                                    "coordinate_mode": "relative",
                                    "duration_ms": 900,
                                    "pause_after_ms": 80,
                                    "button": "left",
                                    "path": [{"x": 220, "y": 240}, {"x": 180, "y": 180}, {"x": 260, "y": 170}],
                                },
                                {
                                    "coordinate_mode": "relative",
                                    "duration_ms": 1100,
                                    "pause_after_ms": 0,
                                    "button": "left",
                                    "path": [{"x": 260, "y": 170}, {"x": 420, "y": 220}, {"x": 500, "y": 360}],
                                },
                            ],
                        },
                    },
                    ensure_ascii=False,
                )
            ),
        )
        observation = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="Paint"),
            visible_windows=[WindowInfo(window_id=1, title="Paint")],
            detected_elements=[],
            ui_tree_summary="Paint canvas visible",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=[],
            recent_actions=[],
        )

        plan = planner.plan("繝壹う繝ｳ繝医〒迪ｫ縺ｮ邱夂判繧呈緒縺・※縺上□縺輔＞", observation, [], {"session_id": "paint-script-demo"})

        self.assertEqual(plan.action.type, ActionType.DRAG)
        self.assertEqual(len(plan.action.pointer_script), 2)
        self.assertEqual(plan.action.pointer_script[0].coordinate_mode, "relative")
        self.assertEqual(plan.action.pointer_script[0].path[1], PointerPoint(180, 180))

    def test_live_planner_parses_shell_execute_action(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=FakeProviderRegistry(
                json.dumps(
                    {
                        "summary": "Run the repository status command.",
                        "reasoning": "Shell is faster than opening a terminal window manually.",
                        "plan_outline": ["Inspect repository", "Decide next step"],
                        "is_complete": False,
                        "completion_reason": "",
                        "action": {
                            "type": "shell_execute",
                            "target": {
                                "window_title": "",
                                "automation_id": "",
                                "name": "",
                                "control_type": "",
                                "fallback_visual_hint": "",
                            },
                            "purpose": "Inspect repository state.",
                            "reason": "A direct shell command is the fastest reliable path.",
                            "preconditions": [],
                            "expected_outcome": "The repository status is available for the next decision.",
                            "risk_level": "low",
                            "confidence": 0.9,
                            "text": "",
                            "hotkey": "",
                            "scroll_amount": 0,
                            "drag_coordinate_mode": "absolute",
                            "drag_path": [],
                            "drag_duration_ms": 0,
                            "pointer_script": [],
                            "shell_kind": "powershell",
                            "shell_command": "git status --short",
                            "shell_cwd": ".",
                            "shell_timeout_seconds": 15,
                            "shell_detach": False,
                            "wait_timeout_ms": 0,
                            "expected_signals": [],
                        },
                    },
                    ensure_ascii=False,
                )
            ),
        )
        observation = Observation(
            screenshot_path=None,
            active_window=WindowInfo(window_id=1, title="AutoCruise CE"),
            visible_windows=[WindowInfo(window_id=1, title="AutoCruise CE")],
            detected_elements=[],
            ui_tree_summary="Desktop ready",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=[],
            recent_actions=[],
        )

        plan = planner.plan("Check the repository status", observation, [], {"session_id": "shell-demo"})

        self.assertEqual(plan.action.type, ActionType.SHELL_EXECUTE)
        self.assertEqual(plan.action.shell_kind, "powershell")
        self.assertEqual(plan.action.shell_command, "git status --short")
        self.assertEqual(plan.action.shell_cwd, ".")
        self.assertEqual(plan.action.shell_timeout_seconds, 15)
        self.assertEqual(plan.action.wait_timeout_ms, 200)
        self.assertEqual(plan.action.expected_signals, [])

    def test_live_planner_uses_stateless_codex_turns(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        client = RecordingProviderClient(
            json.dumps(
                {
                    "summary": "Wait.",
                    "is_complete": False,
                    "action": {
                        "type": "wait",
                        "target": {},
                        "purpose": "Wait for the window to finish loading.",
                        "reason": "The app is still busy.",
                        "preconditions": [],
                        "expected_outcome": "The app becomes ready.",
                        "risk_level": "low",
                        "confidence": 0.6,
                        "text": "",
                        "hotkey": "",
                        "scroll_amount": 0,
                    },
                }
            )
        )

        class RecordingRegistry:
            def get(self, provider: str):
                self.provider = provider
                return client

        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=RecordingRegistry(),
        )
        observation = Observation(
            screenshot_path="demo.ppm",
            active_window=None,
            visible_windows=[],
            detected_elements=[],
            ui_tree_summary="",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=[],
            recent_actions=[],
        )
        plan = planner.plan("Wait for the app", observation, [], {"session_id": "session-123"})
        self.assertIsInstance(plan, PlanStep)
        self.assertFalse(client.session_key)

    def test_live_planner_omits_image_for_structured_observation_and_passes_output_schema(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        client = RecordingProviderClient(
            json.dumps(
                {
                    "summary": "Wait.",
                    "is_complete": False,
                    "action": {
                        "type": "wait",
                        "target": {},
                        "purpose": "Wait for the page to settle.",
                        "reason": "A structured refresh is enough.",
                        "preconditions": [],
                        "expected_outcome": "The page becomes ready.",
                        "risk_level": "low",
                        "confidence": 0.6,
                        "text": "",
                        "hotkey": "",
                        "scroll_amount": 0,
                    },
                }
            )
        )

        class RecordingRegistry:
            def get(self, provider: str):
                return client

        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=RecordingRegistry(),
        )
        observation = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="Edge"),
            visible_windows=[WindowInfo(window_id=1, title="Edge")],
            detected_elements=[],
            ui_tree_summary="Edge browser page",
            cursor_position=(0, 0),
            focused_element="textbox:Search",
            textual_hints=["Edge", "https://example.com"],
            recent_actions=[],
            raw_ref={"observation_kind": ObservationKind.STRUCTURED.value, "vision_fallback_required": False},
        )
        planner.plan("Wait for the page", observation, [], {"session_id": "session-structured"})
        self.assertEqual(client.image_path, "")
        self.assertIsInstance(client.output_schema, dict)
        self.assertIn("expected_signals", client.output_schema["properties"]["action"]["properties"])
        self.assertIn("search_terms", client.output_schema["properties"]["action"]["properties"]["target"]["properties"])
        self.assertIn("backend_hint", client.output_schema["properties"]["action"]["properties"]["target"]["properties"])

    def test_live_planner_prompt_includes_repeat_guard_and_save_flags(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        client = RecordingProviderClient(
            json.dumps(
                {
                    "summary": "Press Ctrl+S.",
                    "reasoning": "The text is already written, so the next missing step is to save it.",
                    "plan_outline": ["save the document"],
                    "is_complete": False,
                    "completion_reason": "",
                    "action": {
                        "type": "hotkey",
                        "target": {
                            "window_title": "Untitled - Notepad",
                            "automation_id": "",
                            "name": "editor_surface",
                            "control_type": "ControlType.Document",
                            "fallback_visual_hint": "editor:window",
                            "search_terms": [],
                            "backend_hint": "",
                        },
                        "purpose": "Save the current document.",
                        "reason": "The user requested saving after writing.",
                        "preconditions": [],
                        "expected_outcome": "The save flow starts.",
                        "risk_level": "low",
                        "confidence": 0.7,
                        "text": "",
                        "hotkey": "CTRL+S",
                        "scroll_amount": 0,
                        "drag_coordinate_mode": "absolute",
                        "drag_path": [],
                        "drag_duration_ms": 0,
                        "pointer_script": [],
                        "shell_kind": "powershell",
                        "shell_command": "",
                        "shell_cwd": "",
                        "shell_timeout_seconds": 20,
                        "shell_detach": False,
                        "wait_timeout_ms": 1000,
                        "expected_signals": [],
                    },
                }
            )
        )

        class RecordingRegistry:
            def get(self, provider: str):
                return client

        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=RecordingRegistry(),
        )
        observation = Observation(
            screenshot_path=None,
            active_window=WindowInfo(window_id=1, title="*Untitled - Notepad", class_name="Notepad"),
            visible_windows=[WindowInfo(window_id=1, title="*Untitled - Notepad", class_name="Notepad")],
            detected_elements=[],
            ui_tree_summary="Notepad editor open",
            cursor_position=(0, 0),
            focused_element="ControlType.Document:Document",
            textual_hints=["Notepad", "editor"],
            recent_actions=[],
            raw_ref={"observation_kind": ObservationKind.STRUCTURED.value, "vision_fallback_required": False},
        )
        recent_actions = [
            Action(
                type=ActionType.TYPE_TEXT,
                target=TargetRef(window_title="Untitled - Notepad", name="editor_surface", control_type="ControlType.Document"),
                purpose="Write the text",
                reason="The editor is ready.",
                preconditions=[],
                expected_outcome="The text appears.",
                text="Hello.",
            ),
            Action(
                type=ActionType.TYPE_TEXT,
                target=TargetRef(window_title="Untitled - Notepad", name="editor_surface", control_type="ControlType.Document"),
                purpose="Write the text",
                reason="The editor is ready.",
                preconditions=[],
                expected_outcome="The text appears.",
                text="Hello.",
            ),
        ]

        planner.plan(
            "Open Notepad, write a self introduction, and save it.",
            observation,
            recent_actions,
            {
                "session_id": "session-repeat",
                "repeat_guard": {
                    "last_action_signature": "type_text|editor_surface|Hello.",
                    "previous_action_signature": "type_text|editor_surface|Hello.",
                    "repeat_streak": 2,
                    "observation_stable": True,
                    "avoid_signature": "type_text|editor_surface|Hello.",
                },
            },
        )

        payload = json.loads(client.prompt)
        self.assertTrue(payload["save_requested"])
        self.assertFalse(payload["save_dialog_visible"])
        self.assertEqual(payload["repeat_guard"]["repeat_streak"], 2)
        self.assertEqual(payload["repeat_guard"]["avoid_signature"], "type_text|editor_surface|Hello.")

    def test_live_planner_repairs_wait_for_active_editor_authoring_task(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        client = RecordingProviderClient(
            [
                json.dumps(
                    {
                        "summary": "Wait.",
                        "reasoning": "The editor might still be settling.",
                        "plan_outline": [],
                        "is_complete": False,
                        "completion_reason": "",
                        "action": {
                            "type": "wait",
                            "target": {
                                "window_title": "繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ",
                                "automation_id": "",
                                "name": "",
                                "control_type": "",
                                "fallback_visual_hint": "",
                                "search_terms": [],
                                "backend_hint": "",
                            },
                            "purpose": "Wait",
                            "reason": "The editor might still be settling.",
                            "preconditions": [],
                            "expected_outcome": "The UI becomes ready.",
                            "risk_level": "low",
                            "confidence": 0.5,
                            "text": "",
                            "hotkey": "",
                            "scroll_amount": 0,
                            "drag_coordinate_mode": "absolute",
                            "drag_path": [],
                            "drag_duration_ms": 0,
                            "pointer_script": [],
                            "shell_kind": "powershell",
                            "shell_command": "",
                            "shell_cwd": "",
                            "shell_timeout_seconds": 20,
                            "shell_detach": False,
                            "wait_timeout_ms": 1000,
                            "expected_signals": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "summary": "Type the draft.",
                        "reasoning": "The editor is already open, so the next concrete step is to write the requested content.",
                        "plan_outline": ["type the draft", "save after writing"],
                        "is_complete": False,
                        "completion_reason": "",
                        "action": {
                            "type": "type_text",
                            "target": {
                                "window_title": "繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ",
                                "automation_id": "",
                                "name": "editor_surface",
                                "control_type": "ControlType.Document",
                                "fallback_visual_hint": "editor:window",
                                "search_terms": ["繝｡繝｢蟶ｳ", "document"],
                                "backend_hint": "uia",
                            },
                            "purpose": "Write the requested text into Notepad.",
                            "reason": "The active editor is ready for input.",
                            "preconditions": [],
                            "expected_outcome": "The editor content updates with the draft.",
                            "risk_level": "low",
                            "confidence": 0.78,
                            "text": "We are improving stable Windows desktop operation.",
                            "hotkey": "",
                            "scroll_amount": 0,
                            "drag_coordinate_mode": "absolute",
                            "drag_path": [],
                            "drag_duration_ms": 0,
                            "pointer_script": [],
                            "shell_kind": "powershell",
                            "shell_command": "",
                            "shell_cwd": "",
                            "shell_timeout_seconds": 20,
                            "shell_detach": False,
                            "wait_timeout_ms": 1200,
                            "expected_signals": [],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )

        class RecordingRegistry:
            def get(self, provider: str):
                return client

        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=RecordingRegistry(),
        )
        observation = Observation(
            screenshot_path=None,
            active_window=WindowInfo(window_id=1, title="繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ", class_name="Notepad"),
            visible_windows=[WindowInfo(window_id=1, title="繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ", class_name="Notepad")],
            detected_elements=[],
            ui_tree_summary="Notepad editor open",
            cursor_position=(0, 0),
            focused_element="ControlType.Document:Document",
            textual_hints=["Notepad", "editor"],
            recent_actions=[],
            raw_ref={"observation_kind": ObservationKind.STRUCTURED.value, "vision_fallback_required": False},
        )
        context = {
            "session_id": "editor-repair",
            "retrieved_context": RetrievedContext(
                goal="Open Notepad and write what you are thinking now.",
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            ),
        }

        plan = planner.plan("Open Notepad and write what you are thinking now.", observation, [], context)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIsNotNone(plan.action)
        self.assertEqual(plan.action.type, ActionType.TYPE_TEXT)
        self.assertEqual(client.calls, 2)

    def test_live_planner_parses_target_search_terms_and_backend_hint(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=FakeProviderRegistry(
                json.dumps(
                    {
                        "summary": "Focus the address bar.",
                        "reasoning": "The browser is open.",
                        "plan_outline": [],
                        "is_complete": False,
                        "completion_reason": "",
                        "action": {
                            "type": "click",
                            "target": {
                                "window_title": "Edge",
                                "automation_id": "",
                                "name": "",
                                "control_type": "ControlType.Edit",
                                "fallback_visual_hint": "",
                                "search_terms": ["address bar", "search bar"],
                                "backend_hint": "playwright",
                            },
                            "purpose": "Focus the address bar.",
                            "reason": "The next step is navigation.",
                            "preconditions": [],
                            "expected_outcome": "The address bar is focused.",
                            "risk_level": "low",
                            "confidence": 0.7,
                            "text": "",
                            "hotkey": "",
                            "scroll_amount": 0,
                            "drag_coordinate_mode": "absolute",
                            "drag_path": [],
                            "drag_duration_ms": 0,
                            "pointer_script": [],
                            "shell_kind": "powershell",
                            "shell_command": "",
                            "shell_cwd": "",
                            "shell_timeout_seconds": 20,
                            "shell_detach": False,
                            "wait_timeout_ms": 1200,
                            "expected_signals": [],
                        },
                    },
                    ensure_ascii=False,
                )
            ),
        )
        observation = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="Edge"),
            visible_windows=[WindowInfo(window_id=1, title="Edge")],
            detected_elements=[],
            ui_tree_summary="Edge browser page",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=[],
            recent_actions=[],
        )

        plan = planner.plan("Open a page in Edge", observation, [], {"session_id": "schema-demo"})

        self.assertEqual(plan.action.target.search_terms, ["address bar", "search bar"])
        self.assertEqual(plan.action.target.backend_hint, "playwright")

    def test_live_planner_uses_contextual_paint_launch_hint_without_code_bias(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=FakeProviderRegistry("{}"),
        )
        context = RetrievedContext(
            goal="Open Paint and draw a cat.",
            stage="initial",
            app_candidates=["paint"],
            task_candidates=["paint_simple_line_drawing"],
            selections=[],
        )
        instructions = planner._build_instructions("Open Paint and draw a cat.", context)
        self.assertIn("Paint -> mspaint", instructions)
        self.assertNotIn("Visual Studio Code -> code", instructions)

    def test_live_planner_prefers_explicit_goal_alias_over_noisy_context(self) -> None:
        settings = type(
            "Settings",
            (),
            {
                "provider": "codex",
                "base_url": "codex app-server",
                "model": "gpt-5.4",
                "timeout_seconds": 30,
                "retry_count": 0,
                "max_tokens": 500,
                "allow_images": True,
                "is_default": True,
            },
        )()
        planner = LiveActionPlanner(
            provider_repo=FakeProviderRepo(settings),
            secret_store=FakeSecretStore(""),
            provider_registry=FakeProviderRegistry("{}"),
        )
        context = RetrievedContext(
            goal="Open Paint and draw a simple cat picture.",
            stage="initial",
            app_candidates=["vscode", "paint"],
            task_candidates=["paint_simple_line_drawing"],
            selections=[],
        )
        instructions = planner._build_instructions("Open Paint and draw a simple cat picture.", context)
        self.assertIn("Paint -> mspaint", instructions)
        self.assertNotIn("Visual Studio Code -> code", instructions)

    def test_provider_defaults_only_include_codex(self) -> None:
        repository = ProviderSettingsRepository(self.paths)
        providers = repository.load()
        self.assertEqual([item.provider for item in providers], ["codex"])
        self.assertEqual(providers[0].base_url, "codex app-server")
        self.assertEqual(providers[0].model, "gpt-5.4")
        self.assertEqual(providers[0].reasoning_effort, "medium")
        self.assertEqual(providers[0].timeout_seconds, 180)
        self.assertEqual(providers[0].retry_count, 0)
        self.assertEqual(providers[0].max_tokens, 2048)
        self.assertEqual(providers[0].service_tier, "auto")
        self.assertTrue(providers[0].allow_images)

    def test_provider_repository_normalizes_stale_settings_to_codex(self) -> None:
        settings_path = self.paths.provider_settings_path()
        settings_path.write_text(
            json.dumps(
                [
                    {
                        "provider": "openai",
                        "base_url": "https://evil.example/v1",
                        "model": "gpt-4.1-mini",
                        "timeout_seconds": 3,
                        "retry_count": 99,
                        "max_tokens": 99999,
                        "is_default": False,
                    },
                    {
                        "provider": "anthropic",
                        "base_url": "https://proxy.example/v1",
                        "model": "claude-3-5-sonnet-latest",
                        "timeout_seconds": 15,
                        "retry_count": 2,
                        "max_tokens": 512,
                        "allow_images": False,
                        "is_default": True,
                    },
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        providers = ProviderSettingsRepository(self.paths).load()
        self.assertEqual([item.provider for item in providers], ["codex"])
        self.assertEqual(providers[0].base_url, "codex app-server")
        self.assertEqual(providers[0].model, "gpt-5.4")
        self.assertEqual(providers[0].reasoning_effort, "medium")
        self.assertEqual(providers[0].timeout_seconds, 180)
        self.assertEqual(providers[0].retry_count, 0)
        self.assertEqual(providers[0].max_tokens, 2048)
        self.assertEqual(providers[0].service_tier, "auto")
        self.assertTrue(providers[0].allow_images)

    def test_provider_repository_preserves_codex_model_and_effort(self) -> None:
        settings_path = self.paths.provider_settings_path()
        settings_path.write_text(
            json.dumps(
                [
                    {
                        "provider": "codex",
                        "base_url": "codex app-server",
                        "model": "gpt-5.4-mini",
                        "reasoning_effort": "low",
                        "timeout_seconds": 120,
                        "retry_count": 1,
                        "max_tokens": 768,
                        "service_tier": "fast",
                        "is_default": True,
                    }
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        provider = ProviderSettingsRepository(self.paths).get_default()
        self.assertEqual(provider.model, "gpt-5.4-mini")
        self.assertEqual(provider.reasoning_effort, "low")
        self.assertEqual(provider.max_tokens, 768)
        self.assertEqual(provider.service_tier, "fast")

    def test_provider_test_connection_uses_image_input(self) -> None:
        client = RecordingProviderClient()
        settings = ProviderSettingsRepository(self.paths).get_default()
        result = client.test_connection(settings, "demo-key")
        self.assertTrue(result.ok)
        self.assertTrue(client.image_path.endswith(".png"))
        self.assertFalse(Path(client.image_path).exists())
        self.assertEqual(client.session_key, "")

    def test_codex_provider_test_connection_uses_live_account_state(self) -> None:
        class FakeAppServer:
            def read_account(self, refresh_token: bool = False):
                _ = refresh_token
                return codex_app_server_module.CodexAccountState(
                    auth_mode="chatgpt",
                    requires_openai_auth=True,
                    email="tester@example.com",
                    plan_type="plus",
                )

        class TestCodexClient(CodexProviderClient):
            def __init__(self, workspace_root: Path, app_server) -> None:
                super().__init__(workspace_root, app_server=app_server)
                self.image_path = ""

            def generate_text(self, settings, api_key, instructions, prompt, image_path=None, session_key=None, output_schema=None):
                _ = settings, api_key, instructions, prompt, session_key, output_schema
                self.image_path = image_path or ""
                return "OK"

        settings = ProviderSettingsRepository(self.paths).get_default()
        client = TestCodexClient(self.temp_dir, FakeAppServer())
        result = client.test_connection(settings, "")
        self.assertTrue(result.ok)
        self.assertTrue(client.image_path.endswith(".png"))

    def test_codex_provider_test_connection_reports_missing_chatgpt_login(self) -> None:
        class FakeAppServer:
            def read_account(self, refresh_token: bool = False):
                _ = refresh_token
                return codex_app_server_module.CodexAccountState(
                    auth_mode=None,
                    requires_openai_auth=True,
                )

        class TestCodexClient(CodexProviderClient):
            def generate_text(self, settings, api_key, instructions, prompt, image_path=None, session_key=None, output_schema=None):
                raise AssertionError("generate_text should not run when auth is missing")

        settings = ProviderSettingsRepository(self.paths).get_default()
        client = TestCodexClient(self.temp_dir, FakeAppServer())
        result = client.test_connection(settings, "")
        self.assertFalse(result.ok)
        self.assertIn("ChatGPT", result.message)

    def test_provider_registry_rejects_custom_provider(self) -> None:
        registry = ProviderRegistry(self.temp_dir)
        with self.assertRaises(ProviderError):
            registry.get("custom")

    def test_provider_registry_supports_codex_provider(self) -> None:
        registry = ProviderRegistry(self.temp_dir)
        self.assertIsNotNone(registry.get("codex"))

    def test_codex_cancel_active_turn_marks_cancel_and_kills_process(self) -> None:
        class FakeProcess:
            pid = 4321

            def poll(self):
                return None

        killed: list[int] = []
        original = codex_app_server_module._terminate_process_tree
        codex_app_server_module._terminate_process_tree = lambda process: killed.append(process.pid)
        try:
            connection = codex_app_server_module.CodexAppServerConnection(self.temp_dir)
            connection._process = FakeProcess()
            connection.cancel_active_turn()
            self.assertTrue(connection.is_cancel_requested())
            self.assertEqual(killed, [4321])
        finally:
            codex_app_server_module._terminate_process_tree = original

    def test_codex_list_models_parses_speed_tiers_and_extended_efforts(self) -> None:
        connection = codex_app_server_module.CodexAppServerConnection(self.temp_dir)
        connection.request = lambda method, params, timeout_seconds=45: {
            "data": [
                {
                    "id": "gpt-5.4",
                    "displayName": "gpt-5.4",
                    "supportedReasoningEfforts": [
                        {"reasoningEffort": "low"},
                        {"reasoningEffort": "medium"},
                        {"reasoningEffort": "high"},
                        {"reasoningEffort": "xhigh"},
                    ],
                    "defaultReasoningEffort": "medium",
                    "inputModalities": ["text", "image"],
                    "additionalSpeedTiers": ["fast"],
                    "isDefault": True,
                }
            ]
        }
        models = connection.list_models()
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].supported_reasoning_efforts, ["low", "medium", "high", "xhigh"])
        self.assertEqual(models[0].supported_service_tiers, ["auto", "fast"])
        self.assertEqual(models[0].display_name, "gpt-5.4")

    def test_uia_client_resolves_packaged_script_path(self) -> None:
        package_root = self.temp_dir / "package"
        script = package_root / "autocruise" / "infrastructure" / "windows" / "uia_client.ps1"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# smoke", encoding="utf-8")

        original_file = uia_client_module.__file__
        original_executable = uia_client_module.sys.executable
        uia_client_module.__file__ = str(package_root / "_internal" / "autocruise" / "infrastructure" / "windows" / "uia_client.py")
        uia_client_module.sys.executable = str(package_root / "AutoCruiseCE.exe")
        try:
            client = UiaClientLayer()
            self.assertEqual(client.script_path, script)
        finally:
            uia_client_module.__file__ = original_file
            uia_client_module.sys.executable = original_executable

    def test_normalize_preferences_migrates_mock_and_drops_legacy_keys(self) -> None:
        normalized = normalize_preferences(
            {
                "language": "ja",
                "default_adapter_mode": "mock",
                "default_provider": "openai",
                "keep_high_risk_screenshots_days": 21,
                "allow_image_send": True,
                "ui": {"refresh_ms": 600},
            }
        )
        self.assertEqual(normalized["language"], "ja")
        self.assertEqual(normalized["default_adapter_mode"], AdapterMode.WINDOWS.value)
        self.assertEqual(normalized["autonomy_mode"], "autonomous")
        self.assertEqual(normalized["pause_hotkey"], "F8")
        self.assertEqual(normalized["stop_hotkey"], "F12")
        self.assertFalse(normalized["max_steps_limit_enabled"])
        self.assertIsNone(normalized["max_steps_per_session"])
        self.assertEqual(normalized["keep_important_screenshots_days"], 21)
        self.assertNotIn("default_provider", normalized)
        self.assertNotIn("keep_high_risk_screenshots_days", normalized)
        self.assertNotIn("allow_image_send", normalized)
        self.assertNotIn("ui", normalized)

    def test_normalize_preferences_migrates_legacy_default_step_limit_to_unlimited(self) -> None:
        normalized = normalize_preferences({"max_steps_per_session": 60})
        self.assertFalse(normalized["max_steps_limit_enabled"])
        self.assertIsNone(normalized["max_steps_per_session"])

    def test_normalize_preferences_preserves_explicit_step_limit(self) -> None:
        normalized = normalize_preferences({"max_steps_per_session": 120})
        self.assertTrue(normalized["max_steps_limit_enabled"])
        self.assertEqual(normalized["max_steps_per_session"], 120)

    def test_workspace_paths_seed_user_files_into_data_root(self) -> None:
        data_root = self.temp_dir / "runtime-data"
        systemprompt_source = self.temp_dir / "users" / "default" / "systemprompt"
        systemprompt_source.mkdir(parents=True, exist_ok=True)
        (systemprompt_source / "AcePilot.md").write_text("# AcePilot", encoding="utf-8")
        paths = WorkspacePaths(self.temp_dir, data_root=data_root)
        paths.ensure()
        self.assertTrue((data_root / "users" / "default" / "provider_settings.json").exists())
        self.assertTrue((data_root / "users" / "default" / "preferences.yaml").exists())
        self.assertTrue((data_root / "users" / "default" / "user_custom_prompt.md").exists())
        self.assertTrue((data_root / "users" / "default" / "systemprompt").exists())
        self.assertEqual(paths.resolve_systemprompt_path("AcePilot.md"), systemprompt_source / "AcePilot.md")

    def test_workspace_paths_refresh_legacy_default_prompt(self) -> None:
        data_root = self.temp_dir / "runtime-data"
        target_dir = data_root / "users" / "default"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "user_custom_prompt.md"
        target.write_text(
            "# Default User Custom Prompt\n\n## Caution Preference\n\nBe slightly cautious by default.\n",
            encoding="utf-8",
        )
        source = self.temp_dir / "users" / "default" / "user_custom_prompt.md"
        source.write_text("# Default User Custom Prompt\n\n## Working Style\n\nAct autonomously.\n", encoding="utf-8")

        paths = WorkspacePaths(self.temp_dir, data_root=data_root)
        paths.ensure()
        refreshed = target.read_text(encoding="utf-8")
        self.assertIn("Act autonomously.", refreshed)
        self.assertNotIn("Caution Preference", refreshed)

    def test_hotkey_normalization_supports_function_keys_and_ctrl_alt(self) -> None:
        self.assertEqual(normalize_hotkey("f8"), "F8")
        self.assertEqual(normalize_hotkey("ctrl+alt+p"), "Ctrl+Alt+P")
        self.assertIsNotNone(hotkey_to_native("F12"))
        self.assertIsNotNone(hotkey_to_native("Ctrl+Alt+S"))

    def test_global_hotkey_manager_polls_when_native_registration_fails(self) -> None:
        manager = GlobalHotkeyManager()
        emitted: list[str] = []
        pressed = False
        manager.activated.connect(emitted.append)
        manager._register_hotkey = lambda hotkey_id, modifiers, vk: False  # type: ignore[method-assign]
        manager._key_down = lambda vk: pressed and vk == 0x7B  # type: ignore[method-assign]
        try:
            failures = manager.apply_bindings({"stop": "F12"})
            self.assertEqual(failures, [])
            manager._poll_bindings()
            self.assertEqual(emitted, [])
            pressed = True
            manager._poll_bindings()
            self.assertEqual(emitted, ["stop"])
            manager._poll_bindings()
            self.assertEqual(emitted, ["stop"])
            pressed = False
            manager._poll_bindings()
            pressed = True
            manager._poll_bindings()
            self.assertEqual(emitted, ["stop", "stop"])
        finally:
            manager.close()

    def test_sanitize_user_message_localizes_common_codex_messages(self) -> None:
        set_locale("ja")
        self.assertIn("ChatGPT", sanitize_user_message("Codex is not signed in with ChatGPT."))
        self.assertIn("接続", sanitize_user_message("Connection confirmed. Text and screenshot input are available."))
        self.assertIn("Codex App Server", sanitize_user_message("Codex App Server is unavailable."))
        set_locale("en")

    def test_translation_key_for_text_maps_status_and_connection_messages_across_locales(self) -> None:
        set_locale("en")
        en_failed = tr("status.failed")
        en_sign_in = tr("message.codex_sign_in_required")
        set_locale("ja")
        ja_failed = tr("status.failed")
        ja_sign_in = tr("message.codex_sign_in_required")
        self.assertEqual(translation_key_for_text(en_failed, prefixes=("status.",)), "status.failed")
        self.assertEqual(translation_key_for_text(ja_failed, prefixes=("status.",)), "status.failed")
        self.assertEqual(
            translation_key_for_text(en_sign_in, prefixes=("message.", "value.", "status.")),
            "message.codex_sign_in_required",
        )
        self.assertEqual(
            translation_key_for_text(ja_sign_in, prefixes=("message.", "value.", "status.")),
            "message.codex_sign_in_required",
        )
        set_locale("en")

    def test_demo_secondary_goal_is_localized(self) -> None:
        set_locale("en")
        self.assertEqual(tr("demo.secondary_goal"), "Open Settings and check Bluetooth status.")
        set_locale("ja")
        self.assertIn("Bluetooth", tr("demo.secondary_goal"))
        set_locale("en")

    def test_finish_visibility_action_restores_or_notifies_after_background_runs(self) -> None:
        self.assertEqual(
            finish_visibility_action(backgrounded=True, trigger="manual", tray_available=True),
            "show_main",
        )
        self.assertEqual(
            finish_visibility_action(backgrounded=True, trigger="scheduled", tray_available=True),
            "notify_tray",
        )
        self.assertEqual(
            finish_visibility_action(backgrounded=True, trigger="scheduled", tray_available=False),
            "show_main",
        )
        self.assertEqual(
            finish_visibility_action(backgrounded=False, trigger="manual", tray_available=True),
            "none",
        )

    def test_build_product_footer_uses_codex_edition_copy(self) -> None:
        product_text, creator_text = build_product_footer("1.0.3", "Sharaku Satoh")
        self.assertEqual(product_text, "AutoCruise Codex Edition Version 1.0.3")
        self.assertEqual(creator_text, "Created by Sharaku Satoh")

    def test_compact_panel_copy_truncates_and_keeps_full_tooltip_text(self) -> None:
        self.assertEqual(compact_panel_copy("Short text", 20), ("Short text", ""))
        compact, tooltip = compact_panel_copy("This is a deliberately long status string for the compact panel.", 24)
        self.assertTrue(compact.endswith("…"))
        self.assertEqual(tooltip, "This is a deliberately long status string for the compact panel.")

    def test_friendly_state_hint_for_planning_omits_safe_wording(self) -> None:
        set_locale("en")
        self.assertNotIn("safe", friendly_state_hint(SessionState.PLANNING.value).lower())
        set_locale("ja")
        self.assertNotIn("螳牙・", friendly_state_hint(SessionState.PLANNING.value))
        set_locale("en")

    def test_codex_sign_in_messages_no_longer_reference_refresh_status(self) -> None:
        set_locale("en")
        self.assertNotIn("Refresh status", tr("message.codex_browser_opened"))
        self.assertNotIn("Refresh status", tr("message.codex_cached_session"))
        set_locale("ja")
        self.assertNotIn("迥ｶ諷九ｒ譖ｴ譁ｰ", tr("message.codex_browser_opened"))
        self.assertNotIn("迥ｶ諷九ｒ譖ｴ譁ｰ", tr("message.codex_cached_session"))
        set_locale("en")

    def test_notice_label_style_uses_expected_color_per_tone(self) -> None:
        self.assertIn("#A7B0BE", notice_label_style("info"))
        self.assertIn("#10A37F", notice_label_style("success"))
        self.assertIn("#D9A441", notice_label_style("warning"))
        self.assertIn("#E85D75", notice_label_style("error"))

    def test_button_text_with_shortcut_appends_hotkey_when_present(self) -> None:
        self.assertEqual(button_text_with_shortcut("Pause", "F8"), "Pause (F8)")
        self.assertEqual(button_text_with_shortcut("Stop", "F12"), "Stop (F12)")
        self.assertEqual(button_text_with_shortcut("Pause", ""), "Pause")

    def test_app_line_edit_uses_native_input_margins(self) -> None:
        editor = AppLineEdit()
        margins = editor.textMargins()
        self.assertTrue(editor.testAttribute(Qt.WA_InputMethodEnabled))
        self.assertEqual((margins.left(), margins.right()), (12, 12))

    def test_app_text_editor_enables_ime_and_document_margin(self) -> None:
        editor = AppTextEditor()
        editor.setPlainText("abc")
        editor.moveCursor(editor.textCursor().MoveOperation.End)
        rect = editor.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)
        self.assertTrue(editor.testAttribute(Qt.WA_InputMethodEnabled))
        self.assertTrue(editor.viewport().testAttribute(Qt.WA_InputMethodEnabled))
        self.assertEqual(int(editor.document().documentMargin()), 12)
        self.assertGreaterEqual(rect.x(), 0)
        self.assertGreaterEqual(rect.y(), 0)

    def test_home_page_goal_input_has_no_placeholder_example(self) -> None:
        page = HomePage()
        self.assertEqual(page.goal_input.placeholderText(), "")
        page.retranslate()
        self.assertEqual(page.goal_input.placeholderText(), "")

    def test_settings_page_treats_blank_max_steps_as_unlimited(self) -> None:
        set_locale("en")
        page = SettingsPage()
        page.set_general_values("en", "autonomous", None, "F8", "F12")
        self.assertEqual(page.max_steps_edit.text(), "")
        self.assertEqual(page.max_steps_edit.placeholderText(), "Unlimited")
        payload = page.general_payload()
        self.assertFalse(payload["max_steps_limit_enabled"])
        self.assertIsNone(payload["max_steps_per_session"])

    def test_settings_page_saves_explicit_max_steps_limit(self) -> None:
        page = SettingsPage()
        page.max_steps_edit.setText("150")
        payload = page.general_payload()
        self.assertTrue(payload["max_steps_limit_enabled"])
        self.assertEqual(payload["max_steps_per_session"], 150)

    def test_settings_page_ai_payload_tracks_service_tier_by_model(self) -> None:
        page = SettingsPage()
        page.set_codex_values(
            command="codex app-server",
            auth_status="ok",
            account="user@example.com",
            result="",
            can_sign_in=False,
            can_sign_out=True,
            model="gpt-5.4",
            reasoning_effort="medium",
            service_tier="fast",
            max_tokens=2048,
            model_options=[("gpt-5.4", "gpt-5.4"), ("GPT-5.4-Mini", "gpt-5.4-mini")],
            effort_catalog={
                "gpt-5.4": ["low", "medium", "high", "xhigh"],
                "gpt-5.4-mini": ["low", "medium", "high"],
            },
            service_tier_catalog={
                "gpt-5.4": ["auto", "fast"],
                "gpt-5.4-mini": ["auto"],
            },
        )
        self.assertEqual(page.service_tier_combo.count(), 2)
        self.assertEqual(page.ai_payload()["service_tier"], "fast")
        page.model_combo.setCurrentText("gpt-5.4-mini")
        self.assertEqual(page.service_tier_combo.count(), 1)
        self.assertEqual(page.service_tier_combo.currentData(), "auto")

    def test_windows_fallback_planner_keeps_progressing(self) -> None:
        toolset = self._make_windows_toolset()
        observation = Observation(
            screenshot_path="before.ppm",
            active_window=WindowInfo(window_id=1, title="Excel"),
            visible_windows=[WindowInfo(window_id=1, title="Excel")],
            detected_elements=[
                DetectedElement(
                    window_id=1,
                    name="Next",
                    control_type="button",
                    bounds=Bounds(100, 120, 120, 40),
                    confidence=0.9,
                )
            ],
            ui_tree_summary="Excel wizard page",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Excel"],
            recent_actions=[],
        )
        recent_actions = [
            Action(
                type=ActionType.FOCUS_WINDOW,
                target=TargetRef(window_title="Excel", name="Excel"),
                purpose="Bring the window forward",
                reason="The app should be active",
                preconditions=[],
                expected_outcome="Excel is active",
                confidence=0.9,
            )
        ]
        plan = toolset.plan_next_action("Continue to the next step in Excel", observation, recent_actions, None)
        self.assertFalse(plan.is_complete)
        self.assertIsNotNone(plan.action)
        self.assertEqual(plan.action.type, ActionType.CLICK)
        self.assertEqual(plan.action.target.name, "Next")

    def test_windows_requested_launch_app_prefers_explicit_goal_over_context_order(self) -> None:
        toolset = self._make_windows_toolset()
        context = RetrievedContext(
            goal="Open Paint and draw a simple cat picture.",
            stage="initial",
            app_candidates=["vscode", "paint"],
            task_candidates=["paint_simple_line_drawing"],
            selections=[],
        )
        app_name = toolset._requested_launch_app("Open Paint and draw a simple cat picture.", context)
        self.assertEqual(app_name, "paint")

    def test_windows_validation_requires_real_change(self) -> None:
        toolset = self._make_windows_toolset()
        previous = self._observation("before.ppm")
        current = self._observation("after.ppm")
        result = toolset.validate_outcome("Button activated", current, previous)
        self.assertFalse(result.success)

    def test_windows_validation_accepts_visual_screenshot_change(self) -> None:
        before_path = self.temp_dir / "before.png"
        after_path = self.temp_dir / "after.png"
        self._write_test_image(before_path, QColor(10, 10, 10))
        self._write_test_image(after_path, QColor(10, 10, 10), accent_rect=(8, 8, 16, 16))

        toolset = self._make_windows_toolset()
        previous = Observation(
            screenshot_path=str(before_path),
            active_window=WindowInfo(window_id=1, title="GIMP"),
            visible_windows=[WindowInfo(window_id=1, title="GIMP")],
            detected_elements=[],
            ui_tree_summary="GIMP canvas",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["GIMP"],
            recent_actions=[],
        )
        current = Observation(
            screenshot_path=str(after_path),
            active_window=WindowInfo(window_id=1, title="GIMP"),
            visible_windows=[WindowInfo(window_id=1, title="GIMP")],
            detected_elements=[],
            ui_tree_summary="GIMP canvas",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["GIMP"],
            recent_actions=[],
        )
        result = toolset.validate_outcome("Draw a visible stroke on the canvas", current, previous)
        self.assertTrue(result.success)

    def test_windows_validation_rejects_unverified_text_entry(self) -> None:
        before_path = self.temp_dir / "before-text.png"
        after_path = self.temp_dir / "after-text.png"
        self._write_test_image(before_path, QColor(25, 25, 25))
        self._write_test_image(after_path, QColor(25, 25, 25), accent_rect=(14, 20, 12, 8))

        action = Action(
            type=ActionType.TYPE_TEXT,
            target=TargetRef(name="Search", control_type="ControlType.Edit", bounds=Bounds(8, 8, 20, 20)),
            purpose="Type the app name",
            reason="The search field should accept text.",
            preconditions=[],
            expected_outcome="Search results reflect the typed query.",
            text="GIMP",
        )
        toolset = self._make_windows_toolset()
        previous = Observation(
            screenshot_path=str(before_path),
            active_window=WindowInfo(window_id=1, title="Search"),
            visible_windows=[WindowInfo(window_id=1, title="Search")],
            detected_elements=[],
            ui_tree_summary="Search panel open",
            cursor_position=(0, 0),
            focused_element="ControlType.Edit:Search",
            textual_hints=["Search"],
            recent_actions=[],
        )
        current = Observation(
            screenshot_path=str(after_path),
            active_window=WindowInfo(window_id=1, title="Search"),
            visible_windows=[WindowInfo(window_id=1, title="Search")],
            detected_elements=[],
            ui_tree_summary="Search panel open",
            cursor_position=(0, 0),
            focused_element="ControlType.Button:SearchButton",
            textual_hints=["Search"],
            recent_actions=[],
        )
        result = toolset.validate_outcome(
            action.expected_outcome,
            current,
            previous_observation=previous,
            action=action,
        )
        self.assertFalse(result.success)
        self.assertIn("could not be verified", result.details)

    def test_windows_validation_accepts_text_entry_when_text_is_visible(self) -> None:
        action = Action(
            type=ActionType.TYPE_TEXT,
            target=TargetRef(name="Search", control_type="ControlType.Edit", bounds=Bounds(8, 8, 20, 20)),
            purpose="Type the app name",
            reason="The search field should accept text.",
            preconditions=[],
            expected_outcome="Search results reflect the typed query.",
            text="GIMP",
        )
        toolset = self._make_windows_toolset()
        previous = Observation(
            screenshot_path="before.ppm",
            active_window=WindowInfo(window_id=1, title="Search"),
            visible_windows=[WindowInfo(window_id=1, title="Search")],
            detected_elements=[],
            ui_tree_summary="Search panel open",
            cursor_position=(0, 0),
            focused_element="ControlType.Edit:Search",
            textual_hints=["Search"],
            recent_actions=[],
        )
        current = Observation(
            screenshot_path="after.ppm",
            active_window=WindowInfo(window_id=1, title="Search"),
            visible_windows=[WindowInfo(window_id=1, title="Search")],
            detected_elements=[DetectedElement(window_id=1, name="GIMP", control_type="ControlType.ListItem", confidence=0.8)],
            ui_tree_summary="Search panel open with GIMP result",
            cursor_position=(0, 0),
            focused_element="ControlType.Edit:Search",
            textual_hints=["Search", "GIMP"],
            recent_actions=[],
        )
        result = toolset.validate_outcome(
            action.expected_outcome,
            current,
            previous_observation=previous,
            action=action,
        )
        self.assertTrue(result.success)

    def test_windows_validation_accepts_successful_editor_input_without_visible_ocr_text(self) -> None:
        action = Action(
            type=ActionType.TYPE_TEXT,
            target=TargetRef(
                window_title="Untitled - Notepad",
                control_type="ControlType.Document",
                bounds=Bounds(100, 100, 900, 640),
                fallback_visual_hint="editor:window",
            ),
            purpose="Type into Notepad",
            reason="The editor is ready.",
            preconditions=[],
            expected_outcome="The editor content updates.",
            text="縺薙ｓ縺ｫ縺｡縺ｯ",
        )
        toolset = self._make_windows_toolset()
        previous = Observation(
            screenshot_path="before.ppm",
            active_window=WindowInfo(window_id=1, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640)),
            visible_windows=[WindowInfo(window_id=1, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640))],
            detected_elements=[],
            ui_tree_summary="Notepad editor window.",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Notepad"],
            recent_actions=[],
        )
        current = Observation(
            screenshot_path="after.ppm",
            active_window=WindowInfo(window_id=1, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640)),
            visible_windows=[WindowInfo(window_id=1, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640))],
            detected_elements=[],
            ui_tree_summary="Notepad editor window.",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Notepad"],
            recent_actions=[],
            raw_ref={"last_execution": {"success": True, "details": "Pasted text: 5 chars", "error": "", "payload": {}}},
        )
        result = toolset.validate_outcome(
            action.expected_outcome,
            current,
            previous_observation=previous,
            action=action,
        )
        self.assertTrue(result.success)

    def test_windows_observation_builder_includes_focused_element_and_visible_hints(self) -> None:
        source = self.temp_dir / "source.png"
        self._write_test_image(source, QColor(30, 30, 30))
        active_window = WindowInfo(window_id=1, title="Search")
        focused = DetectedElement(
            window_id=1,
            name="Search",
            automation_id="SearchEditBox",
            control_type="ControlType.Edit",
            bounds=Bounds(40, 40, 220, 32),
            confidence=0.9,
        )
        elements = [
            DetectedElement(window_id=1, name="GIMP", control_type="ControlType.ListItem", confidence=0.78),
            focused,
        ]
        builder = WindowsObservationBuilder(
            screenshot_provider=StaticScreenshotProvider(source),
            window_manager=StaticWindowManager(active_window, [active_window]),
            uia_adapter=FocusAwareUIAAdapter(elements, focused),
        )
        observation = builder.capture(self.temp_dir / "capture.png", [])
        self.assertEqual(observation.focused_element, "ControlType.Edit:Search")
        self.assertIn("GIMP", observation.textual_hints)
        self.assertIn("SearchEditBox", observation.textual_hints)
        self.assertIn("screen_bounds", observation.raw_ref)
        self.assertEqual(observation.raw_ref["visual_guides"]["cursor_position"]["x"], 320)
        self.assertEqual(observation.raw_ref["automation"]["priority"][0], "uia")
        self.assertTrue(observation.raw_ref["automation"]["availability"]["uia"])
        self.assertFalse(observation.raw_ref["automation"]["availability"]["playwright"])

    def test_windows_capture_observation_reuses_previous_snapshot_and_still_calls_live_planner(self) -> None:
        previous = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="Excel", process_id=123),
            visible_windows=[WindowInfo(window_id=1, title="Excel", process_id=123)],
            detected_elements=[
                DetectedElement(window_id=1, name="Next", control_type="button", bounds=Bounds(100, 120, 120, 40), confidence=0.9)
            ],
            ui_tree_summary="Excel wizard page",
            cursor_position=(0, 0),
            focused_element="ControlType.Button:Next",
            textual_hints=["Excel", "Next"],
            recent_actions=[],
            raw_ref={
                "sensor_snapshot": asdict(
                    PrimarySensorSnapshot(
                        active_window=WindowInfo(window_id=1, title="Excel", process_id=123),
                        focused_element="ControlType.Button:Next",
                        event_counts={},
                        active_automation_backend="uia",
                        fingerprint="stable-fingerprint",
                    )
                ),
                "observation_kind": ObservationKind.FULL.value,
                "vision_fallback_required": False,
            },
        )
        builder = RecordingObservationBuilder(previous)
        live_planner = CountingLivePlanner()
        sensor = StaticPrimarySensorHub(
            [
                PrimarySensorSnapshot(
                    active_window=WindowInfo(window_id=1, title="Excel", process_id=123),
                    focused_element="ControlType.Button:Next",
                    event_counts={},
                    active_automation_backend="uia",
                    fingerprint="stable-fingerprint",
                )
            ]
        )
        toolset = WindowsAgentToolset(
            root=self.temp_dir,
            observation_builder=builder,
            window_manager=DummyWindowManager(),
            input_executor=DummyInputExecutor(),
            uia_adapter=DummyUIAAdapter(),
            live_planner=live_planner,
            primary_sensor=sensor,
        )
        observation = toolset.capture_observation("demo", previous_observation=previous, recent_actions=[])
        self.assertEqual(builder.full_calls, 0)
        self.assertEqual(builder.reuse_calls, 1)
        self.assertEqual(observation.raw_ref["planner_skip_reason"], "sensor_unchanged")
        plan = toolset.plan_next_action("Continue to the next step in Excel", observation, [], None)
        self.assertEqual(live_planner.calls, 1)
        self.assertEqual(plan.action.type, ActionType.CLICK)

    def test_windows_observation_builder_numbers_ui_candidates_and_separates_ocr_text(self) -> None:
        source = self.temp_dir / "source.png"
        self._write_test_image(source, QColor(30, 30, 30))
        active_window = WindowInfo(window_id=1, title="Chrome", bounds=Bounds(20, 20, 800, 600))
        automation_element = AutomationElementState(
            backend=AutomationBackend.UIA,
            element_id="uia-1",
            name="Address and search bar",
            automation_id="Omnibox",
            control_type="ControlType.Edit",
            bounds=Bounds(120, 52, 500, 32),
            patterns=[AutomationOperation.VALUE],
        )

        class AutomationAdapterStub:
            backend = AutomationBackend.UIA

            def enumerate(self, *, scope: str = "active", limit: int = 50):
                _ = scope, limit
                return [automation_element]

            def find(self, query: str, *, limit: int = 20):
                _ = query, limit
                return []

        builder = WindowsObservationBuilder(
            screenshot_provider=StaticScreenshotProvider(source),
            window_manager=StaticWindowManager(active_window, [active_window]),
            uia_adapter=FocusAwareUIAAdapter([], None),
            automation_router=AutomationRouter([AutomationAdapterStub()]),
        )

        observation = builder.capture(self.temp_dir / "capture-ui.png", [])

        ui_candidates = observation.raw_ref["screen_understanding"]["ui_candidates"]
        self.assertEqual(ui_candidates[0]["candidate_index"], 1)
        self.assertEqual(ui_candidates[0]["name"], "Address and search bar")
        self.assertEqual(observation.raw_ref["screen_understanding"]["ocr_text_blocks"], [])
        self.assertFalse(observation.raw_ref["screen_understanding"]["ocr_available"])

    def test_windows_wait_for_expected_change_uses_structured_refresh_when_uia_signal_matches(self) -> None:
        previous = Observation(
            screenshot_path="before.png",
            active_window=WindowInfo(window_id=1, title="Search", process_id=321),
            visible_windows=[WindowInfo(window_id=1, title="Search", process_id=321)],
            detected_elements=[],
            ui_tree_summary="Search panel open",
            cursor_position=(0, 0),
            focused_element="ControlType.Edit:Search",
            textual_hints=["Search"],
            recent_actions=[],
            raw_ref={
                "sensor_snapshot": asdict(
                    PrimarySensorSnapshot(
                        active_window=WindowInfo(window_id=1, title="Search", process_id=321),
                        focused_element="ControlType.Edit:Search",
                        event_counts={},
                        active_automation_backend="uia",
                        fingerprint="before",
                    )
                ),
                "observation_kind": ObservationKind.FULL.value,
                "vision_fallback_required": False,
            },
        )
        builder = RecordingObservationBuilder(previous)
        sensor = StaticPrimarySensorHub(
            [PrimarySensorSnapshot(active_window=WindowInfo(window_id=1, title="Search"), focused_element="ControlType.Edit:Search", event_counts={}, active_automation_backend="uia", fingerprint="before")],
            wait_result={
                "matched": True,
                "snapshot": PrimarySensorSnapshot(
                    active_window=WindowInfo(window_id=1, title="Search", process_id=321),
                    focused_element="ControlType.Edit:Search",
                    event_counts={"focus_changed": 1},
                    active_automation_backend="uia",
                    fingerprint="after",
                    has_events=True,
                ),
                "matched_signal": "focus_changed",
                "wait_satisfied_by": "uia_event",
            },
        )
        toolset = WindowsAgentToolset(
            root=self.temp_dir,
            observation_builder=builder,
            window_manager=DummyWindowManager(),
            input_executor=DummyInputExecutor(),
            uia_adapter=DummyUIAAdapter(),
            live_planner=None,
            primary_sensor=sensor,
        )
        action = Action(
            type=ActionType.TYPE_TEXT,
            target=TargetRef(name="Search", control_type="ControlType.Edit", bounds=Bounds(8, 8, 20, 20)),
            purpose="Type the app name",
            reason="The search field should accept text.",
            preconditions=[],
            expected_outcome="Search results reflect the typed query.",
            text="Paint",
            expected_signals=[ExpectedSignal(ExpectedSignalKind.FOCUS_CHANGED, target="Search")],
        )
        observation = toolset.wait_for_expected_change("demo", action, previous, recent_actions=[])
        self.assertIsNone(observation.screenshot_path)
        self.assertEqual(builder.structured_calls, 1)
        self.assertEqual(builder.vision_calls, 0)
        self.assertEqual(observation.raw_ref["wait_satisfied_by"], "uia_event")

    def test_windows_wait_for_expected_change_uses_vision_fallback_for_canvas_drag(self) -> None:
        previous = Observation(
            screenshot_path="before.png",
            active_window=WindowInfo(window_id=1, title="Paint", process_id=654),
            visible_windows=[WindowInfo(window_id=1, title="Paint", process_id=654)],
            detected_elements=[],
            ui_tree_summary="Paint canvas ready",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Paint"],
            recent_actions=[],
            raw_ref={
                "sensor_snapshot": asdict(
                    PrimarySensorSnapshot(
                        active_window=WindowInfo(window_id=1, title="Paint", process_id=654),
                        focused_element="",
                        event_counts={},
                        active_automation_backend="uia",
                        fingerprint="paint-before",
                    )
                ),
                "observation_kind": ObservationKind.FULL.value,
                "vision_fallback_required": False,
            },
        )
        builder = RecordingObservationBuilder(previous)
        sensor = StaticPrimarySensorHub(
            [PrimarySensorSnapshot(active_window=WindowInfo(window_id=1, title="Paint"), focused_element="", event_counts={}, active_automation_backend="uia", fingerprint="paint-before")],
            wait_result={
                "matched": False,
                "snapshot": PrimarySensorSnapshot(
                    active_window=WindowInfo(window_id=1, title="Paint", process_id=654),
                    focused_element="",
                    event_counts={},
                    active_automation_backend="uia",
                    fingerprint="paint-after",
                ),
                "matched_signal": "",
                "wait_satisfied_by": "",
            },
        )
        toolset = WindowsAgentToolset(
            root=self.temp_dir,
            observation_builder=builder,
            window_manager=DummyWindowManager(),
            input_executor=DummyInputExecutor(),
            uia_adapter=DummyUIAAdapter(),
            live_planner=None,
            primary_sensor=sensor,
        )
        action = Action(
            type=ActionType.DRAG,
            target=TargetRef(name="Canvas", control_type="ControlType.Pane", bounds=Bounds(100, 120, 600, 400)),
            purpose="Draw the first curve",
            reason="The canvas is ready for a visible stroke.",
            preconditions=[],
            expected_outcome="A visible stroke appears.",
            drag_path=[PointerPoint(120, 140), PointerPoint(140, 160)],
            expected_signals=[ExpectedSignal(ExpectedSignalKind.VISION_CHANGE, target="Canvas")],
        )
        observation = toolset.wait_for_expected_change("demo", action, previous, recent_actions=[])
        self.assertEqual(builder.vision_calls, 1)
        self.assertEqual(observation.raw_ref["observation_kind"], ObservationKind.VISION_FALLBACK.value)
        self.assertTrue(observation.screenshot_path.endswith(".png"))

    def test_match_expected_signals_accepts_structured_fingerprint_change_for_value_update(self) -> None:
        previous = PrimarySensorSnapshot(
            active_window=WindowInfo(window_id=1, title="Chrome", process_id=100),
            focused_element="Edit:Address and search bar",
            event_counts={},
            active_automation_backend="playwright",
            fingerprint="before",
            metadata={
                "browser": {
                    "available": True,
                    "title": "Old",
                    "url": "https://example.com/old",
                    "focused_element": "INPUT:Address",
                    "focused_role": "textbox",
                    "fingerprint": "browser-before",
                }
            },
        )
        current = PrimarySensorSnapshot(
            active_window=WindowInfo(window_id=1, title="Chrome", process_id=100),
            focused_element="Edit:Address and search bar",
            event_counts={},
            active_automation_backend="playwright",
            fingerprint="after",
            metadata={
                "browser": {
                    "available": True,
                    "title": "New",
                    "url": "https://example.com/new",
                    "focused_element": "INPUT:Address",
                    "focused_role": "textbox",
                    "fingerprint": "browser-after",
                }
            },
        )

        matched = match_expected_signals(previous, current, [ExpectedSignal(ExpectedSignalKind.VALUE_CHANGED, target="Address")])

        self.assertIsNotNone(matched)
        self.assertEqual(matched.kind, ExpectedSignalKind.VALUE_CHANGED)

    def test_uia_client_parses_core_properties_and_patterns(self) -> None:
        payload = {
            "element_id": "42.100",
            "name": "Submit",
            "automation_id": "SubmitButton",
            "class_name": "Button",
            "control_type": "ControlType.Button",
            "bounding_rectangle": {"left": 10, "top": 20, "width": 100, "height": 32},
            "is_enabled": True,
            "has_keyboard_focus": False,
            "runtime_id": [42, 100],
            "process_id": 1234,
            "patterns": ["Invoke", "LegacyIAccessible"],
        }
        client = FakeUiaClient({"root": payload})

        element = client.root()

        self.assertIsNotNone(element)
        self.assertEqual(element.name, "Submit")
        self.assertEqual(element.automation_id, "SubmitButton")
        self.assertEqual(element.class_name, "Button")
        self.assertEqual(element.control_type, "ControlType.Button")
        self.assertEqual(element.runtime_id, "42.100")
        self.assertEqual(element.process_id, 1234)
        self.assertEqual(element.bounds, Bounds(10, 20, 100, 32))
        self.assertIn(AutomationOperation.INVOKE, element.patterns)
        self.assertIn(AutomationOperation.LEGACY_IACCESSIBLE, element.patterns)

    def test_uia_adapter_executes_click_before_pointer_fallback(self) -> None:
        payload = {
            "elements": [
                {
                    "element_id": "42.200",
                    "name": "Submit",
                    "automation_id": "SubmitButton",
                    "control_type": "ControlType.Button",
                    "bounding_rectangle": {"left": 10, "top": 20, "width": 100, "height": 32},
                    "runtime_id": [42, 200],
                    "patterns": ["Invoke"],
                }
            ]
        }
        click_result = {"ok": True, "message": "Invoked element.", "operation": "Invoke"}
        uia_adapter = UIAAdapter(FakeUiaClient({"find": payload, "click": click_result}))
        toolset = WindowsAgentToolset(
            root=self.temp_dir,
            observation_builder=DummyObservationBuilder(),
            window_manager=DummyWindowManager(),
            input_executor=RaisingInputExecutor(),
            uia_adapter=uia_adapter,
            live_planner=None,
        )
        action = Action(
            type=ActionType.CLICK,
            target=TargetRef(name="Submit", automation_id="SubmitButton"),
            purpose="Submit",
            reason="Button is available",
            preconditions=[],
            expected_outcome="Submitted",
        )

        result = toolset.execute_action(action)

        self.assertTrue(result.success)
        self.assertIn("uia:invoke", result.details)

    def test_automation_router_uses_structured_adapter_before_vision_fallback(self) -> None:
        element = AutomationElementState(
            backend=AutomationBackend.UIA,
            element_id="42.300",
            name="Submit",
            patterns=[AutomationOperation.INVOKE],
        )

        class Adapter:
            backend = AutomationBackend.UIA

            def enumerate(self, *, scope: str = "active", limit: int = 50):
                return [element]

        router = AutomationRouter([Adapter()])

        elements = router.enumerate()

        self.assertEqual(elements, [element])
        self.assertFalse(router.should_use_vision_fallback(elements))

    def test_automation_router_resolve_target_prefers_backend_hint_and_search_terms(self) -> None:
        uia_element = AutomationElementState(
            backend=AutomationBackend.UIA,
            element_id="uia-1",
            name="Address field",
            automation_id="AddressField",
            control_type="ControlType.Edit",
            role="textbox",
        )
        playwright_element = AutomationElementState(
            backend=AutomationBackend.PLAYWRIGHT,
            element_id="pw-1",
            name="Address and search bar",
            automation_id="omnibox",
            control_type="textbox",
            role="textbox",
        )

        class UiaAdapter:
            backend = AutomationBackend.UIA

            def find(self, query: str, *, limit: int = 20):
                _ = limit
                return [uia_element] if "address" in query.lower() else []

        class PlaywrightAdapterStub:
            backend = AutomationBackend.PLAYWRIGHT

            def find(self, query: str, *, limit: int = 20):
                _ = limit
                return [playwright_element] if "search bar" in query.lower() else []

        router = AutomationRouter([UiaAdapter(), PlaywrightAdapterStub()])

        resolved = router.resolve_target(
            TargetRef(
                control_type="textbox",
                search_terms=["search bar", "address bar"],
                backend_hint="playwright",
            )
        )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.backend, AutomationBackend.PLAYWRIGHT)
        self.assertEqual(resolved.element_id, "pw-1")

    def test_playwright_adapter_uses_locator_first_priority(self) -> None:
        page = FakePlaywrightPage()
        adapter = PlaywrightAdapter(page)

        elements = adapter.find("Submit", limit=1)

        self.assertEqual(page.calls[0], "role:button")
        self.assertEqual(elements[0].backend, AutomationBackend.PLAYWRIGHT)
        self.assertEqual(elements[0].name, "Submit")
        self.assertIn(AutomationOperation.CLICK, elements[0].patterns)

    def test_playwright_adapter_can_fallback_to_cdp_input_domain(self) -> None:
        page = FakePlaywrightPage()
        page.locator_obj = FakeLocator(click_raises=True)
        cdp = FakeCdp()
        adapter = PlaywrightAdapter(page, cdp=cdp)
        element = adapter.find("Submit", limit=1)[0]

        result = adapter.click(element)

        self.assertTrue(result.success)
        self.assertEqual(cdp.clicked_at, (70, 40))

    def test_visual_guidance_annotation_marks_cursor_and_window(self) -> None:
        image = QImage(400, 300, QImage.Format_RGB32)
        image.fill(QColor("#101418"))
        state = build_visual_guide_state(
            Bounds(0, 0, 400, 300),
            (120, 90),
            WindowInfo(window_id=1, title="GIMP", bounds=Bounds(80, 60, 160, 120)),
        )
        annotated = annotate_image(image, state)
        self.assertNotEqual(annotated.pixelColor(120, 90).name(), "#101418")
        self.assertNotEqual(annotated.pixelColor(80, 60).name(), "#101418")
        self.assertFalse(state.prompt_payload()["show_grid"])
        self.assertFalse(state.prompt_payload()["show_text_labels"])
        self.assertFalse(state.prompt_payload()["show_legend"])

    def test_floating_control_widget_accepts_brand_pixmap(self) -> None:
        widget = FloatingControlWidget()
        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor("#10a37f"))

        widget.set_logo_pixmap(pixmap)

        logo = widget.logo_label.pixmap()
        self.assertIsNotNone(logo)
        self.assertFalse(logo.isNull())
        self.assertEqual(widget.logo_label.width(), 30)
        self.assertIn("background: transparent", widget.logo_label.styleSheet())
        self.assertIn("font-size: 21px", widget.title_label.styleSheet())
        self.assertIn("font-weight: 300", widget.title_label.styleSheet())

    def test_main_brand_title_uses_light_weight(self) -> None:
        stylesheet = build_stylesheet()

        self.assertIn('QLabel[role="brand"]', stylesheet)
        self.assertIn("font-weight: 300;", stylesheet)

    def test_windows_verify_target_uses_global_uia_lookup_for_visual_plan_targets(self) -> None:
        search_box = DetectedElement(
            window_id=None,
            name="讀懃ｴ｢",
            automation_id="SearchButton",
            control_type="ControlType.Button",
            bounds=Bounds(653, 1040, 220, 32),
            confidence=0.62,
        )
        toolset = WindowsAgentToolset(
            root=self.temp_dir,
            observation_builder=DummyObservationBuilder(),
            window_manager=DummyWindowManager(),
            input_executor=DummyInputExecutor(),
            uia_adapter=QueryAwareUIAAdapter({"讀懃ｴ｢": [search_box], "SearchButton": [search_box]}),
            live_planner=None,
        )
        action = Action(
            type=ActionType.CLICK,
            target=TargetRef(
                name="讀懃ｴ｢",
                automation_id="SearchButton",
                control_type="ControlType.Edit",
                bounds=Bounds(464, 742, 96, 24),
                fallback_visual_hint="Windows taskbar search box labeled 讀懃ｴ｢ near the bottom center of the screen",
            ),
            purpose="Bring up Windows Search so GIMP can be launched.",
            reason="GIMP is not visible.",
            preconditions=["The taskbar is visible."],
            expected_outcome="Windows Search opens.",
            confidence=0.98,
        )
        observation = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="AutoCruiseCE"),
            visible_windows=[WindowInfo(window_id=1, title="AutoCruiseCE")],
            detected_elements=[],
            ui_tree_summary="Active=AutoCruiseCE; windows=['AutoCruiseCE']; elements=[]",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["AutoCruiseCE"],
            recent_actions=[],
        )
        verification = toolset.verify_target(action, observation)
        self.assertTrue(verification.matched)
        self.assertIn("Matching", verification.reason)
        self.assertEqual(action.target.bounds, search_box.bounds)
        self.assertEqual(action.target.automation_id, "SearchButton")

    def test_windows_verify_target_allows_hotkeys_without_pointer_targets(self) -> None:
        toolset = self._make_windows_toolset()
        action = Action(
            type=ActionType.HOTKEY,
            target=TargetRef(),
            purpose="Open Windows Search",
            reason="The app is not visible yet.",
            preconditions=[],
            expected_outcome="Windows Search opens.",
            hotkey="WIN+S",
            confidence=0.97,
        )
        observation = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="AutoCruiseCE"),
            visible_windows=[WindowInfo(window_id=1, title="AutoCruiseCE")],
            detected_elements=[],
            ui_tree_summary="Desktop",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Desktop"],
            recent_actions=[],
        )
        verification = toolset.verify_target(action, observation)
        self.assertTrue(verification.matched)
        self.assertIn("Hotkey", verification.reason)

    def test_windows_toolset_prefers_direct_process_launch_for_paint(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Paint and draw a simple cat line art.",
                stage="initial",
                app_candidates=["paint"],
                task_candidates=["paint_simple_line_drawing"],
                selections=[],
            )
        }
        observation = Observation(
            screenshot_path="demo.png",
            active_window=WindowInfo(window_id=1, title="AutoCruiseCE"),
            visible_windows=[WindowInfo(window_id=1, title="AutoCruiseCE")],
            detected_elements=[],
            ui_tree_summary="Desktop visible",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Desktop"],
            recent_actions=[],
        )
        plan = toolset.plan_next_action("Open Paint and draw a simple cat line art.", observation, [], context)
        self.assertEqual(plan.action.type, ActionType.SHELL_EXECUTE)
        self.assertEqual(plan.action.shell_kind, "process")
        self.assertEqual(plan.action.shell_command, "mspaint")
        self.assertTrue(plan.action.shell_detach)
        self.assertEqual(plan.action.target.fallback_visual_hint, "launch:paint")

    def test_windows_toolset_falls_back_to_run_dialog_after_failed_process_launch(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Paint and draw a simple cat line art.",
                stage="initial",
                app_candidates=["paint"],
                task_candidates=["paint_simple_line_drawing"],
                selections=[],
            )
        }
        edit = DetectedElement(
            window_id=1,
            name="Open",
            automation_id="RunTextBox",
            control_type="ControlType.Edit",
            bounds=Bounds(40, 80, 240, 24),
            confidence=0.84,
        )
        observation = Observation(
            screenshot_path="run.png",
            active_window=WindowInfo(window_id=1, title="Run"),
            visible_windows=[WindowInfo(window_id=1, title="Run")],
            detected_elements=[edit],
            ui_tree_summary="Run dialog open",
            cursor_position=(0, 0),
            focused_element="ControlType.Edit:Open",
            textual_hints=["Run", "Open"],
            recent_actions=[],
            raw_ref={
                "last_execution": {
                    "success": True,
                    "details": "Started detached process",
                    "error": "",
                    "payload": {"kind": "process", "command": "mspaint"},
                }
            },
        )
        plan = toolset.plan_next_action(
            "Open Paint and draw a simple cat line art.",
            observation,
            [],
            {
                **context,
                "recent_failure_reason": "paint is not visible yet",
            },
        )
        self.assertEqual(plan.action.type, ActionType.TYPE_TEXT)
        self.assertEqual(plan.action.text, "mspaint")

    def test_windows_toolset_prefers_direct_process_launch_for_notepad(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Notepad and write a paragraph.",
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            )
        }
        observation = Observation(
            screenshot_path="desktop.png",
            active_window=WindowInfo(window_id=1, title="Desktop"),
            visible_windows=[WindowInfo(window_id=1, title="Desktop")],
            detected_elements=[],
            ui_tree_summary="Desktop visible",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Desktop"],
            recent_actions=[],
        )

        plan = toolset.plan_next_action("Open Notepad and write a paragraph.", observation, [], context)

        self.assertEqual(plan.action.type, ActionType.SHELL_EXECUTE)
        self.assertEqual(plan.action.shell_kind, "process")
        self.assertEqual(plan.action.shell_command, "notepad")
        self.assertTrue(plan.action.shell_detach)
        self.assertEqual(plan.action.target.fallback_visual_hint, "launch:notepad")

    def test_windows_toolset_types_requested_text_into_active_notepad_without_waiting(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal='Open Notepad and write "hello".',
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            )
        }
        observation = Observation(
            screenshot_path="notepad.png",
            active_window=WindowInfo(window_id=10, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640)),
            visible_windows=[WindowInfo(window_id=10, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640))],
            detected_elements=[],
            ui_tree_summary="Notepad editor window is open.",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Notepad", "editor"],
            recent_actions=[],
        )

        plan = toolset.plan_next_action('Open Notepad and write "hello".', observation, [], context)

        self.assertEqual(plan.action.type, ActionType.TYPE_TEXT)
        self.assertEqual(plan.action.text, "hello")
        self.assertEqual(plan.action.target.window_title, "Untitled - Notepad")
        self.assertEqual(plan.action.target.fallback_visual_hint, "editor:window")

    def test_windows_toolset_does_not_synthesize_text_for_generic_notepad_writing_goal(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Notepad and write a short sentence.",
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            )
        }
        observation = Observation(
            screenshot_path="notepad.png",
            active_window=WindowInfo(window_id=10, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640)),
            visible_windows=[WindowInfo(window_id=10, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640))],
            detected_elements=[],
            ui_tree_summary="Notepad editor window is open.",
            cursor_position=(0, 0),
            focused_element="ControlType.Document:Document",
            textual_hints=["Notepad", "editor"],
            recent_actions=[],
        )

        plan = toolset.plan_next_action("Open Notepad and write a short sentence.", observation, [], context)

        self.assertIsNotNone(plan.action)
        self.assertEqual(plan.action.type, ActionType.WAIT)

    def test_windows_toolset_does_not_synthesize_self_introduction_for_notepad_goal(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Notepad and write a self introduction.",
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            )
        }
        observation = Observation(
            screenshot_path="notepad.png",
            active_window=WindowInfo(window_id=10, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640)),
            visible_windows=[WindowInfo(window_id=10, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640))],
            detected_elements=[],
            ui_tree_summary="Notepad editor window is open.",
            cursor_position=(0, 0),
            focused_element="ControlType.Document:Document",
            textual_hints=["Notepad", "editor"],
            recent_actions=[],
        )

        plan = toolset.plan_next_action("Open Notepad and write a self introduction.", observation, [], context)

        self.assertIsNotNone(plan.action)
        self.assertEqual(plan.action.type, ActionType.WAIT)

    def test_windows_toolset_does_not_auto_complete_after_successful_editor_text_entry(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Notepad and write a self introduction.",
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            )
        }
        text = "Hello. I am AutoCruise CE, a Windows desktop operator."
        observation = Observation(
            screenshot_path="notepad.png",
            active_window=WindowInfo(window_id=10, title="*Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640)),
            visible_windows=[WindowInfo(window_id=10, title="*Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 100, 900, 640))],
            detected_elements=[],
            ui_tree_summary="Notepad editor window is open.",
            cursor_position=(0, 0),
            focused_element="ControlType.Document:Document",
            textual_hints=["Notepad", "editor", text],
            recent_actions=[],
            raw_ref={"last_execution": {"success": True, "details": "Pasted text", "error": "", "payload": {}}},
        )
        recent_actions = [
            Action(
                type=ActionType.TYPE_TEXT,
                target=TargetRef(window_title="Untitled - Notepad", control_type="ControlType.Document"),
                purpose="Type into Notepad",
                reason="The editor is ready.",
                preconditions=[],
                expected_outcome="The editor content updates.",
                text=text,
            )
        ]

        plan = toolset.plan_next_action("Open Notepad and write a self introduction.", observation, recent_actions, context)

        self.assertTrue(plan.is_complete)
        self.assertIsNone(plan.action)

    def test_windows_toolset_does_not_repeat_editor_text_when_title_changes_after_edit(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Notepad, write a self introduction.",
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            )
        }
        text = "Hello. I am AutoCruise CE, a Windows desktop operator."
        observation = Observation(
            screenshot_path="notepad-after.png",
            active_window=WindowInfo(
                window_id=10,
                title="*Hello. I am AutoCruise CE, a Windows desktop operator. - Notepad",
                class_name="Notepad",
                bounds=Bounds(100, 100, 900, 640),
            ),
            visible_windows=[
                WindowInfo(
                    window_id=10,
                    title="*Hello. I am AutoCruise CE, a Windows desktop operator. - Notepad",
                    class_name="Notepad",
                    bounds=Bounds(100, 100, 900, 640),
                )
            ],
            detected_elements=[],
            ui_tree_summary="Notepad editor window is open.",
            cursor_position=(0, 0),
            focused_element="ControlType.Document:Document",
            textual_hints=["Notepad", text],
            recent_actions=[],
            raw_ref={"last_execution": {"success": True, "details": "Pasted text", "error": "", "payload": {}}},
        )
        recent_actions = [
            Action(
                type=ActionType.TYPE_TEXT,
                target=TargetRef(
                    window_title="Untitled - Notepad",
                    name="editor_surface",
                    control_type="ControlType.Document",
                    fallback_visual_hint="editor:window",
                ),
                purpose="Type into Notepad",
                reason="The editor is ready.",
                preconditions=[],
                expected_outcome="The editor content updates.",
                text=text,
            )
        ]

        plan = toolset.plan_next_action("Open Notepad, write a self introduction.", observation, recent_actions, context)

        self.assertTrue(plan.is_complete)
        self.assertIsNone(plan.action)

    def test_windows_toolset_requests_save_after_successful_editor_text_entry(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Notepad, write a self introduction, and save it.",
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            )
        }
        text = "Hello. I am AutoCruise CE, a Windows desktop operator."
        observation = Observation(
            screenshot_path="notepad-after.png",
            active_window=WindowInfo(
                window_id=10,
                title="*Hello. I am AutoCruise CE, a Windows desktop operator. - Notepad",
                class_name="Notepad",
                bounds=Bounds(100, 100, 900, 640),
            ),
            visible_windows=[
                WindowInfo(
                    window_id=10,
                    title="*Hello. I am AutoCruise CE, a Windows desktop operator. - Notepad",
                    class_name="Notepad",
                    bounds=Bounds(100, 100, 900, 640),
                )
            ],
            detected_elements=[],
            ui_tree_summary="Notepad editor window is open.",
            cursor_position=(0, 0),
            focused_element="ControlType.Document:Document",
            textual_hints=["Notepad", text],
            recent_actions=[],
            raw_ref={"last_execution": {"success": True, "details": "Pasted text", "error": "", "payload": {}}},
        )
        recent_actions = [
            Action(
                type=ActionType.TYPE_TEXT,
                target=TargetRef(
                    window_title="Untitled - Notepad",
                    name="editor_surface",
                    control_type="ControlType.Document",
                    fallback_visual_hint="editor:window",
                ),
                purpose="Type into Notepad",
                reason="The editor is ready.",
                preconditions=[],
                expected_outcome="The editor content updates.",
                text=text,
            )
        ]

        plan = toolset.plan_next_action("Open Notepad, write a self introduction, and save it.", observation, recent_actions, context)

        self.assertFalse(plan.is_complete)
        self.assertIsNotNone(plan.action)
        self.assertEqual(plan.action.type, ActionType.WAIT)

    def test_windows_toolset_handles_save_dialog_after_ctrl_s(self) -> None:
        toolset = self._make_windows_toolset()
        context = {
            "retrieved_context": RetrievedContext(
                goal="Open Notepad, write a self introduction, and save it.",
                stage="initial",
                app_candidates=["notepad"],
                task_candidates=["notepad_simple_writing"],
                selections=[],
            )
        }
        observation = Observation(
            screenshot_path="save-dialog.png",
            active_window=WindowInfo(
                window_id=11,
                title="Save As",
                class_name="#32770",
                bounds=Bounds(140, 140, 900, 620),
            ),
            visible_windows=[
                WindowInfo(
                    window_id=11,
                    title="Save As",
                    class_name="#32770",
                    bounds=Bounds(140, 140, 900, 620),
                )
            ],
            detected_elements=[
                DetectedElement(
                    window_id=11,
                    name="File name",
                    automation_id="1001",
                    control_type="ControlType.Edit",
                    bounds=Bounds(220, 680, 420, 24),
                    confidence=0.9,
                )
            ],
            ui_tree_summary="Save As dialog open.",
            cursor_position=(0, 0),
            focused_element="ControlType.Edit:File name",
            textual_hints=["Save As", "File name"],
            recent_actions=[],
            raw_ref={"last_execution": {"success": True, "details": "Pressed Ctrl+S", "error": "", "payload": {}}},
        )
        recent_actions = [
            Action(
                type=ActionType.TYPE_TEXT,
                target=TargetRef(
                    window_title="Untitled - Notepad",
                    name="editor_surface",
                    control_type="ControlType.Document",
                    fallback_visual_hint="editor:window",
                ),
                purpose="Type into Notepad",
                reason="The editor is ready.",
                preconditions=[],
                expected_outcome="The editor content updates.",
                text="Hello. I am AutoCruise CE, a Windows desktop operator.",
            ),
            Action(
                type=ActionType.HOTKEY,
                target=TargetRef(
                    window_title="Untitled - Notepad",
                    name="editor_surface",
                    control_type="ControlType.Document",
                    fallback_visual_hint="editor:save-request",
                ),
                purpose="Save the document",
                reason="The goal requires saving.",
                preconditions=[],
                expected_outcome="The document save flow starts.",
                hotkey="CTRL+S",
            ),
        ]

        plan = toolset.plan_next_action("Open Notepad, write a self introduction, and save it.", observation, recent_actions, context)

        self.assertIsNotNone(plan.action)
        self.assertEqual(plan.action.type, ActionType.WAIT)

    def test_windows_validation_requires_real_paint_window_for_launch_marker(self) -> None:
        toolset = self._make_windows_toolset()
        previous = self._observation("before.ppm")
        action = Action(
            type=ActionType.HOTKEY,
            target=TargetRef(fallback_visual_hint="launch:paint"),
            purpose="Launch Paint",
            reason="Run dialog is ready",
            preconditions=[],
            expected_outcome="Paint window is visible.",
            confidence=0.95,
            hotkey="ENTER",
        )
        current = Observation(
            screenshot_path="after.ppm",
            active_window=WindowInfo(window_id=1, title="Desktop"),
            visible_windows=[WindowInfo(window_id=1, title="Desktop")],
            detected_elements=[],
            ui_tree_summary="Desktop still visible",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Desktop"],
            recent_actions=[],
        )
        result = toolset.validate_outcome(action.expected_outcome, current, previous_observation=previous, action=action)
        self.assertFalse(result.success)
        self.assertIn("paint is not visible yet", result.details.lower())

    def test_windows_validation_accepts_notepad_launch_marker_from_window_class(self) -> None:
        toolset = self._make_windows_toolset()
        previous = self._observation("before.ppm")
        action = Action(
            type=ActionType.SHELL_EXECUTE,
            target=TargetRef(
                window_title="Notepad",
                name="Notepad",
                fallback_visual_hint="launch:notepad",
            ),
            purpose="Launch Notepad",
            reason="Direct process launch is the shortest path.",
            preconditions=[],
            expected_outcome="Notepad is visible.",
            confidence=0.96,
            shell_kind="process",
            shell_command="notepad",
            shell_detach=True,
        )
        current = Observation(
            screenshot_path=None,
            active_window=WindowInfo(window_id=20, title="繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ", class_name="Notepad"),
            visible_windows=[WindowInfo(window_id=20, title="繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ", class_name="Notepad")],
            detected_elements=[],
            ui_tree_summary="Japanese Notepad window visible",
            cursor_position=(0, 0),
            focused_element="ControlType.Document:Text Editor",
            textual_hints=["繝｡繝｢蟶ｳ"],
            recent_actions=[],
            raw_ref={
                "last_execution": {
                    "success": True,
                    "details": "Started detached process",
                    "error": "",
                    "payload": {"pid": 1234, "detach": True},
                }
            },
        )

        result = toolset.validate_outcome(action.expected_outcome, current, previous_observation=previous, action=action)

        self.assertTrue(result.success)
        self.assertIn("notepad", result.details.lower())

    def test_windows_verify_target_refines_drag_to_paint_canvas_bounds(self) -> None:
        toolset = self._make_windows_toolset()
        canvas = DetectedElement(
            window_id=1,
            name="Canvas",
            automation_id="PaintCanvas",
            control_type="ControlType.Pane",
            bounds=Bounds(320, 300, 700, 420),
            confidence=0.92,
        )
        observation = Observation(
            screenshot_path="paint.png",
            active_window=WindowInfo(window_id=1, title="Untitled - Paint", bounds=Bounds(260, 160, 860, 640)),
            visible_windows=[WindowInfo(window_id=1, title="Untitled - Paint", bounds=Bounds(260, 160, 860, 640))],
            detected_elements=[canvas],
            ui_tree_summary="Paint canvas visible",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Paint", "Canvas"],
            recent_actions=[],
        )
        action = Action(
            type=ActionType.DRAG,
            target=TargetRef(
                window_title="Untitled - Paint",
                control_type="ControlType.Window",
                bounds=Bounds(260, 160, 860, 640),
            ),
            purpose="Draw on the canvas",
            reason="A visible canvas is available",
            preconditions=[],
            expected_outcome="A line appears on the canvas",
            confidence=0.88,
            drag_coordinate_mode="relative",
            drag_path=[PointerPoint(100, 100), PointerPoint(300, 300)],
            drag_duration_ms=600,
        )
        result = toolset.verify_target(action, observation)
        self.assertTrue(result.matched)
        self.assertEqual(action.target.bounds, canvas.bounds)
        self.assertEqual(action.target.automation_id, "PaintCanvas")

    def test_windows_validation_allows_wait_progress(self) -> None:
        toolset = self._make_windows_toolset()
        previous = self._observation("before.ppm")
        current = self._observation("after.ppm")
        result = toolset.validate_outcome("Wait completed and the window remains responsive", current, previous)
        self.assertTrue(result.success)

    def test_mock_toolset_captures_png_screenshots(self) -> None:
        toolset = MockAgentToolset(
            root=self.temp_dir,
        )
        observation = toolset.capture_observation("demo")
        self.assertTrue(observation.screenshot_path.endswith(".png"))
        self.assertTrue(Path(observation.screenshot_path).exists())

    def test_scheduled_job_repository_round_trip(self) -> None:
        repository = ScheduledJobRepository(self.paths)
        job = ScheduledJob(
            task_id="daily_excel",
            instruction="Open Excel and prepare the workbook.",
            run_at="09:00",
            recurrence=ScheduleKind.DAILY,
            enabled=True,
        )
        repository.upsert(job)
        recorded_at = utc_now()
        repository.record_result("daily_excel", ScheduledJobState.COMPLETED, "Finished", recorded_at)

        saved = repository.get("daily_excel")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.recurrence, ScheduleKind.DAILY)
        self.assertEqual(saved.last_result, ScheduledJobState.COMPLETED)
        self.assertEqual(saved.last_message, "Finished")
        self.assertEqual(saved.last_run_at, recorded_at)

    def test_scheduled_job_repository_skips_invalid_entries(self) -> None:
        self.paths.scheduled_jobs_path().write_text(
            json.dumps(
                [
                    {
                        "task_id": "daily_excel",
                        "instruction": "Open Excel and prepare the workbook.",
                        "run_at": "09:00",
                        "recurrence": "daily",
                        "enabled": True,
                    },
                    {
                        "task_id": "broken_enum",
                        "instruction": "Broken recurrence value.",
                        "run_at": "09:00",
                        "recurrence": "sometimes",
                        "enabled": True,
                    },
                    {
                        "instruction": "Missing task id.",
                        "run_at": "09:00",
                        "recurrence": "daily",
                        "enabled": True,
                    },
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        jobs = ScheduledJobRepository(self.paths).load()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].task_id, "daily_excel")
        self.assertEqual(jobs[0].recurrence, ScheduleKind.DAILY)

    def test_load_scheduled_jobs_formats_items(self) -> None:
        repository = ScheduledJobRepository(self.paths)
        repository.upsert(
            ScheduledJob(
                task_id="weekly_settings",
                instruction="Open Windows Settings and check Bluetooth.",
                run_at="18:30",
                recurrence=ScheduleKind.WEEKLY,
                enabled=False,
                weekdays=["Monday"],
                last_result=ScheduledJobState.SKIPPED,
                last_message="Skipped",
                last_run_at=utc_now(),
            )
        )

        items = load_scheduled_jobs(self.paths)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["task_id"], "weekly_settings")
        self.assertEqual(items[0]["recurrence"], "weekly")
        self.assertEqual(items[0]["weekday"], "Monday")
        self.assertIn("Weekly", items[0]["summary"])
        self.assertEqual(items[0]["tone"], "error")

    def test_load_session_detail_formats_history_without_creating_capture_folder(self) -> None:
        set_locale("en")
        append_jsonl(
            self.paths.logs_dir / "session_history.jsonl",
            {
                "session_id": "sess-1",
                "instruction": "Open Paint",
                "result": "success",
                "target_app": "paint",
                "executed_at": "2026-04-08T10:30:00",
                "step_count": 3,
            },
        )

        detail = load_session_detail(self.paths, "sess-1")

        self.assertEqual(detail["history"]["display_time"], "2026-04-08 10:30")
        self.assertEqual(detail["history"]["display_result"], "Success")
        self.assertEqual(detail["history"]["display_app"], "Paint")
        self.assertFalse((self.paths.screenshots_dir / "session_sess-1").exists())
        self.assertEqual(detail["captures"], [])

    def test_delete_session_thread_removes_related_logs_and_captures(self) -> None:
        for path, record in (
            (
                self.paths.logs_dir / "session_history.jsonl",
                {"session_id": "sess-1", "instruction": "Delete me"},
            ),
            (
                self.paths.logs_dir / "session_history.jsonl",
                {"session_id": "sess-2", "instruction": "Keep me"},
            ),
            (
                self.paths.logs_dir / "audit_log.jsonl",
                {"session_id": "sess-1", "type": "state_transition"},
            ),
            (
                self.paths.logs_dir / "execution_log.jsonl",
                {"session_id": "sess-1", "type": "action"},
            ),
        ):
            append_jsonl(path, record)

        session_one_capture = self.paths.session_screenshot_dir("sess-1") / "step-1.png"
        session_one_capture.write_bytes(b"png")
        session_two_capture = self.paths.session_screenshot_dir("sess-2") / "step-1.png"
        session_two_capture.write_bytes(b"png")

        deleted = delete_session_thread(self.paths, "sess-1")

        self.assertTrue(deleted)
        self.assertEqual(
            [item.get("session_id") for item in read_jsonl(self.paths.logs_dir / "session_history.jsonl")],
            ["sess-2"],
        )
        self.assertEqual(read_jsonl(self.paths.logs_dir / "audit_log.jsonl"), [])
        self.assertEqual(read_jsonl(self.paths.logs_dir / "execution_log.jsonl"), [])
        self.assertFalse((self.paths.screenshots_dir / "session_sess-1").exists())
        self.assertTrue((self.paths.screenshots_dir / "session_sess-2").exists())

    def test_history_page_enables_thread_actions_only_for_loaded_detail(self) -> None:
        page = HistoryPage()

        self.assertFalse(page.diagnostics_button.isEnabled())
        self.assertFalse(page.delete_button.isEnabled())

        page.set_records([{"session_id": "sess-1"}])
        self.assertFalse(page.diagnostics_button.isEnabled())
        self.assertFalse(page.delete_button.isEnabled())

        page.show_detail("2026-04-08 | Success | Paint", "Goal: Open Paint", [])
        self.assertTrue(page.diagnostics_button.isEnabled())
        self.assertTrue(page.delete_button.isEnabled())
        self.assertTrue(page.capture_list.isHidden())

        page.clear_detail()
        self.assertFalse(page.diagnostics_button.isEnabled())
        self.assertFalse(page.delete_button.isEnabled())

    def test_windows_distribution_files_exist(self) -> None:
        spec_path = ROOT / "AutoCruise.spec"
        batch_path = ROOT / "build_windows.bat"
        installer_path = ROOT / "installer" / "AutoCruiseCE.iss"
        icon_path = ROOT / "autocruise_logo.ico"
        screenshot_path = ROOT / "docs" / "ui-renewal-home.png"
        readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertTrue(spec_path.exists())
        self.assertTrue(batch_path.exists())
        self.assertTrue(installer_path.exists())
        self.assertTrue(icon_path.exists())
        self.assertIn("PyInstaller", spec_path.read_text(encoding="utf-8"))
        self.assertIn("version=version_info", spec_path.read_text(encoding="utf-8"))
        self.assertIn("optimize=1", spec_path.read_text(encoding="utf-8"))
        self.assertIn("docs", spec_path.read_text(encoding="utf-8"))
        self.assertIn("users/default/systemprompt", spec_path.read_text(encoding="utf-8"))
        self.assertIn("APP_NAME", spec_path.read_text(encoding="utf-8"))
        self.assertNotIn('"models"', spec_path.read_text(encoding="utf-8"))
        self.assertNotIn('"runtime"', spec_path.read_text(encoding="utf-8"))
        self.assertNotIn("uia_query.ps1", spec_path.read_text(encoding="utf-8"))
        self.assertIn("autocruise_logo.ico", spec_path.read_text(encoding="utf-8"))
        self.assertIn("autocruise_logo.png", spec_path.read_text(encoding="utf-8"))
        self.assertIn("Compress-Archive", batch_path.read_text(encoding="utf-8"))
        self.assertIn("iscc", batch_path.read_text(encoding="utf-8").lower())
        self.assertIn("AutoCruiseCE.exe", batch_path.read_text(encoding="utf-8"))
        self.assertIn("%RELEASE_DIR%\\AutoCruise", batch_path.read_text(encoding="utf-8"))
        self.assertNotIn("ensure_bundled_runtime", batch_path.read_text(encoding="utf-8"))
        self.assertIn("img.save", batch_path.read_text(encoding="utf-8"))
        self.assertIn("AppVersion", installer_path.read_text(encoding="utf-8"))
        self.assertIn("OutputBaseFilename=AutoCruiseCE-Setup", installer_path.read_text(encoding="utf-8"))
        self.assertTrue(screenshot_path.exists())
        self.assertIn("docs/ui-renewal-home.png", readme_text)
        self.assertIn("release\\AutoCruiseCE\\AutoCruiseCE.exe", readme_text)
        self.assertIn("portable", readme_text.lower())
        self.assertIn("installer", readme_text.lower())
        self.assertIn("Codex App Server", readme_text)
        self.assertIn("ChatGPT sign-in", readme_text)
        self.assertNotIn("Local Model", readme_text)
        self.assertNotIn("GGUF", readme_text)
        self.assertNotIn("llama.cpp", readme_text)
        self.assertNotIn("models/", readme_text)
        self.assertNotIn("runtime/", readme_text)
        self.assertIn("build_windows.bat", readme_text)
        self.assertIn("--run-task <task_id>", readme_text)
        self.assertIn("Windows Task Scheduler", readme_text)
        self.assertTrue((ROOT / "docs" / "release_qa_checklist.md").exists())
        self.assertTrue((ROOT / "src" / "autocruise" / "infrastructure" / "windows" / "uia_client.ps1").exists())
        self.assertFalse((ROOT / "src" / "autocruise" / "infrastructure" / "windows" / "uia_query.ps1").exists())
        self.assertFalse((ROOT / "src" / "autocruise" / "infrastructure" / "local_models.py").exists())
        self.assertFalse((ROOT / "models").exists())
        self.assertFalse((ROOT / "runtime").exists())

    def test_public_documents_do_not_reference_removed_designs(self) -> None:
        forbidden = (
            "local model",
            "llama.cpp",
            "OpenAI API key",
            "Anthropic",
            "approval panel",
            "Tkinter",
        )
        document_paths = [
            ROOT / "README.md",
            ROOT / "information.md",
            ROOT / "docs" / "architecture.md",
            ROOT / "docs" / "release_qa_checklist.md",
        ]
        for path in document_paths:
            text = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                self.assertNotIn(term.lower(), text, f"{term} remains in {path}")

    def test_uia_client_script_prefetches_properties_and_patterns(self) -> None:
        script = (ROOT / "src" / "autocruise" / "infrastructure" / "windows" / "uia_client.ps1").read_text(encoding="utf-8")
        for property_name in (
            "NameProperty",
            "AutomationIdProperty",
            "ClassNameProperty",
            "ControlTypeProperty",
            "BoundingRectangleProperty",
            "IsEnabledProperty",
            "HasKeyboardFocusProperty",
            "RuntimeIdProperty",
            "ProcessIdProperty",
        ):
            self.assertIn(property_name, script)
        for pattern_name in (
            "InvokePattern",
            "ValuePattern",
            "SelectionItemPattern",
            "ExpandCollapsePattern",
            "TogglePattern",
            "ScrollPattern",
            "TextPattern",
            "WindowPattern",
            "LegacyIAccessible",
        ):
            self.assertIn(pattern_name, script)
        self.assertIn("CacheRequest", script)
        self.assertIn("FindAllBuildCache", script)
        self.assertIn('"root"', script)
        self.assertIn('"focused"', script)
        self.assertIn('"from_point"', script)
        self.assertIn('"active_descendants"', script)

    def test_windows_api_signatures_are_configured_for_handles(self) -> None:
        self.assertIsNotNone(screenshot_user32.GetDC.argtypes)
        self.assertIsNotNone(gdi32.CreateCompatibleBitmap.argtypes)
        self.assertIsNotNone(window_user32.EnumWindows.argtypes)
        self.assertIsNotNone(window_user32.GetForegroundWindow.restype)
        self.assertIsNotNone(window_user32.GetCursorPos.argtypes)

    def test_input_executor_structs_use_configured_sendinput_layout(self) -> None:
        self.assertIsNotNone(input_user32.SetCursorPos.argtypes)
        self.assertIsNotNone(input_user32.SendInput.argtypes)
        self.assertGreaterEqual(ctypes.sizeof(KEYBDINPUT), ctypes.sizeof(ctypes.c_void_p) + 12)
        self.assertGreaterEqual(ctypes.sizeof(INPUT), ctypes.sizeof(KEYBDINPUT))

    def test_input_executor_supports_windows_and_named_hotkeys(self) -> None:
        executor = InputExecutor(DummyWindowManager())
        self.assertEqual(executor._vk_for_key("win"), VK_LWIN)
        self.assertEqual(executor._vk_for_key("enter"), VK_RETURN)
        self.assertEqual(executor._vk_for_key("f5"), 0x74)

    def test_input_executor_skips_click_for_taskbar_search_typing(self) -> None:
        executor = InputExecutor(DummyWindowManager())
        action = Action(
            type=ActionType.TYPE_TEXT,
            target=TargetRef(control_type="ControlType.Edit", bounds=Bounds(470, 735, 180, 31)),
            purpose="Type into Windows Search",
            reason="The search box should already have focus.",
            preconditions=[],
            expected_outcome="Search results appear.",
            text="GIMP",
        )
        original = input_user32.GetSystemMetrics
        input_user32.GetSystemMetrics = lambda index: 768
        try:
            self.assertFalse(executor._should_click_before_typing(action))
        finally:
            input_user32.GetSystemMetrics = original

    def test_input_executor_clicks_before_typing_browser_document_target(self) -> None:
        executor = InputExecutor(DummyWindowManager())
        action = Action(
            type=ActionType.TYPE_TEXT,
            target=TargetRef(
                window_title="Chrome",
                name="Web content",
                control_type="ControlType.Pane",
                bounds=Bounds(200, 240, 560, 42),
            ),
            purpose="Type into browser field",
            reason="Browser fields are often exposed without UIA ValuePattern.",
            preconditions=[],
            expected_outcome="Text appears in the browser field.",
            text="hello",
        )
        self.assertTrue(executor._should_click_before_typing(action))

    def test_input_executor_prefers_virtual_key_text_for_ascii(self) -> None:
        executor = InputExecutor(DummyWindowManager())
        key_events: list[tuple[int, int]] = []
        unicode_packets: list[int] = []
        original_vk = input_user32.VkKeyScanW
        original_keybd = input_user32.keybd_event
        original_sendinput = input_user32.SendInput
        input_user32.VkKeyScanW = lambda char: ord(char.upper())
        input_user32.keybd_event = lambda vk, scan, flags, extra: key_events.append((vk, flags))

        def fake_sendinput(count, pointer, size):
            unicode_packets.append(count)
            return count

        input_user32.SendInput = fake_sendinput
        try:
            ok, details = executor._send_text("GIMP")
        finally:
            input_user32.VkKeyScanW = original_vk
            input_user32.keybd_event = original_keybd
            input_user32.SendInput = original_sendinput
        self.assertTrue(ok)
        self.assertIn("4 chars", details)
        self.assertGreaterEqual(len(key_events), 8)
        self.assertEqual(unicode_packets, [])

    def test_input_executor_pastes_non_ascii_text_via_clipboard(self) -> None:
        executor = InputExecutor(DummyWindowManager())
        clipboard_writes: list[str] = []
        hotkeys: list[str] = []

        executor._read_clipboard_text = lambda: "before"
        executor._write_clipboard_text = lambda text: clipboard_writes.append(text)

        def fake_hotkey(combo: str) -> tuple[bool, str]:
            hotkeys.append(combo)
            return True, f"Sent hotkey {combo}"

        executor._send_hotkey = fake_hotkey

        ok, details = executor._send_text("縺薙ｓ縺ｫ縺｡縺ｯ")

        self.assertTrue(ok)
        self.assertIn("Pasted text", details)
        self.assertEqual(clipboard_writes, ["縺薙ｓ縺ｫ縺｡縺ｯ", "before"])
        self.assertEqual(hotkeys, ["CTRL+V"])

    def test_input_executor_focuses_window_using_launch_marker_app_key(self) -> None:
        lookups: list[str] = []
        focused: list[int] = []

        class MarkerWindowManager:
            def find_window(self, title: str):
                lookups.append(title)
                if title == "notepad":
                    return WindowInfo(window_id=44, title="繧ｿ繧､繝医Ν縺ｪ縺・- 繝｡繝｢蟶ｳ", class_name="Notepad")
                return None

            def focus_window(self, window_id: int) -> bool:
                focused.append(window_id)
                return True

        executor = InputExecutor(MarkerWindowManager())
        action = Action(
            type=ActionType.TYPE_TEXT,
            target=TargetRef(fallback_visual_hint="launch:notepad"),
            purpose="Type into Notepad",
            reason="Notepad should receive focus.",
            preconditions=[],
            expected_outcome="The text appears in Notepad.",
            text="hello",
        )

        executor._focus_target_window(action)

        self.assertEqual(lookups, ["notepad"])
        self.assertEqual(focused, [44])

    def test_input_executor_clicks_window_anchor_and_prefers_paste_for_notepad_document(self) -> None:
        cursor_positions: list[tuple[int, int]] = []
        mouse_events: list[int] = []
        original_set_cursor = input_user32.SetCursorPos
        original_mouse_event = input_user32.mouse_event
        original_sleep = time.sleep
        input_user32.SetCursorPos = lambda x, y: cursor_positions.append((x, y)) or True
        input_user32.mouse_event = lambda flags, dx, dy, data, extra: mouse_events.append(flags)
        time.sleep = lambda seconds: None

        class EditorWindowManager:
            def find_window(self, title: str):
                if title in {"Notepad", "Document"}:
                    return WindowInfo(window_id=51, title="Untitled - Notepad", class_name="Notepad", bounds=Bounds(100, 80, 500, 360))
                return None

            def find_editable_child(self, window_id: int):
                if window_id == 51:
                    return WindowInfo(window_id=52, title="", class_name="RichEditD2DPT", bounds=Bounds(120, 120, 420, 260))
                return None

            def focus_window(self, window_id: int) -> bool:
                return window_id == 51

        executor = InputExecutor(EditorWindowManager())
        paste_preferences: list[bool] = []
        original_send_text = executor._send_text
        executor._send_text = lambda text, *, prefer_paste=False: paste_preferences.append(prefer_paste) or (True, f"Typed text: {len(text)} chars")
        try:
            ok, _ = executor.execute(
                Action(
                    type=ActionType.TYPE_TEXT,
                    target=TargetRef(window_title="Notepad", name="Document", control_type="ControlType.Document"),
                    purpose="Type into Notepad",
                    reason="The editor should receive input.",
                    preconditions=[],
                    expected_outcome="Text appears in the editor.",
                    text="hello world",
                )
            )
        finally:
            executor._send_text = original_send_text
            input_user32.SetCursorPos = original_set_cursor
            input_user32.mouse_event = original_mouse_event
            time.sleep = original_sleep

        self.assertTrue(ok)
        self.assertEqual(cursor_positions, [(330, 250)])
        self.assertEqual(mouse_events[:2], [0x0002, 0x0004])
        self.assertEqual(paste_preferences, [True])

    def test_input_executor_maps_relative_drag_points_to_canvas_bounds(self) -> None:
        executor = InputExecutor(DummyWindowManager())
        action = Action(
            type=ActionType.DRAG,
            target=TargetRef(bounds=Bounds(100, 200, 400, 300)),
            purpose="Draw a curve",
            reason="Canvas is ready",
            preconditions=[],
            expected_outcome="A curve appears",
            drag_coordinate_mode="relative",
            drag_path=[PointerPoint(0, 0), PointerPoint(500, 500), PointerPoint(1000, 1000)],
        )
        self.assertEqual(executor._drag_points(action), [(100, 200), (300, 350), (500, 500)])

    def test_input_executor_executes_multi_stroke_pointer_script(self) -> None:
        executor = InputExecutor(DummyWindowManager())
        drags: list[tuple[list[tuple[int, int]], int]] = []
        sleeps: list[float] = []

        def fake_drag(points: list[tuple[int, int]], duration_ms: int) -> None:
            drags.append((points, duration_ms))

        def fake_focus(action: Action) -> None:
            _ = action

        original_sleep = time.sleep
        executor._drag_pointer = fake_drag
        executor._focus_target_window = fake_focus
        time.sleep = lambda seconds: sleeps.append(seconds)
        try:
            ok, details = executor.execute(
                Action(
                    type=ActionType.DRAG,
                    target=TargetRef(bounds=Bounds(100, 200, 400, 300)),
                    purpose="Draw the line art",
                    reason="Canvas is ready",
                    preconditions=[],
                    expected_outcome="The sketch appears",
                    pointer_script=[
                        PointerStroke(
                            coordinate_mode="relative",
                            duration_ms=700,
                            pause_after_ms=90,
                            path=[PointerPoint(0, 0), PointerPoint(500, 500)],
                        ),
                        PointerStroke(
                            coordinate_mode="relative",
                            duration_ms=800,
                            pause_after_ms=0,
                            path=[PointerPoint(500, 500), PointerPoint(1000, 1000)],
                        ),
                    ],
                )
            )
        finally:
            time.sleep = original_sleep

        self.assertTrue(ok)
        self.assertIn("2 strokes", details)
        self.assertEqual(drags[0], ([(100, 200), (300, 350)], 700))
        self.assertEqual(drags[1], ([(300, 350), (500, 500)], 800))
        self.assertEqual(sleeps, [0.09])

    def test_windows_execute_action_catches_executor_exceptions(self) -> None:
        toolset = WindowsAgentToolset(
            root=self.temp_dir,
            observation_builder=DummyObservationBuilder(),
            window_manager=DummyWindowManager(),
            input_executor=RaisingInputExecutor(),
            uia_adapter=DummyUIAAdapter(),
            live_planner=None,
        )
        result = toolset.execute_action(
            Action(
                type=ActionType.TYPE_TEXT,
                target=TargetRef(name="Search"),
                purpose="Type text",
                reason="The field is ready.",
                preconditions=[],
                expected_outcome="Search text appears.",
                text="GIMP",
            )
        )
        self.assertFalse(result.success)
        self.assertIn("boom", result.error)

    def test_shell_executor_runs_cmd_and_captures_output(self) -> None:
        executor = ShellExecutor(self.temp_dir)
        action = Action(
            type=ActionType.SHELL_EXECUTE,
            target=TargetRef(),
            purpose="Inspect shell output",
            reason="A command-line check is fastest.",
            preconditions=[],
            expected_outcome="The output is captured.",
            shell_kind="cmd",
            shell_command="echo hello-from-autocruise",
            shell_timeout_seconds=10,
        )

        result = executor.execute(action)

        self.assertTrue(result.success)
        self.assertEqual(result.payload.get("exit_code"), 0)
        self.assertIn("hello-from-autocruise", result.payload.get("stdout", "").lower())

    def test_windows_toolset_routes_shell_execute_and_validates_from_execution_result(self) -> None:
        observation = Observation(
            screenshot_path=None,
            active_window=WindowInfo(window_id=1, title="Visual Studio Code"),
            visible_windows=[WindowInfo(window_id=1, title="Visual Studio Code")],
            detected_elements=[],
            ui_tree_summary="VS Code workspace",
            cursor_position=(0, 0),
            focused_element="editor",
            textual_hints=["workspace"],
            recent_actions=[],
            raw_ref={"observation_kind": ObservationKind.STRUCTURED.value},
        )
        snapshot = PrimarySensorSnapshot(
            active_window=observation.active_window,
            focused_element="editor",
            event_counts={},
            active_automation_backend="uia",
            fingerprint="shell-snapshot",
        )
        builder = RecordingObservationBuilder(observation)
        shell_result = ExecutionResult(
            success=True,
            details="cmd exited with code 0. hello",
            payload={
                "kind": "cmd",
                "command": "echo hello",
                "cwd": str(self.temp_dir),
                "detach": False,
                "exit_code": 0,
                "stdout": "hello",
                "stderr": "",
            },
        )
        shell_executor = DummyShellExecutor(shell_result)
        toolset = WindowsAgentToolset(
            root=self.temp_dir,
            observation_builder=builder,
            window_manager=DummyWindowManager(),
            input_executor=DummyInputExecutor(),
            uia_adapter=DummyUIAAdapter(),
            live_planner=None,
            primary_sensor=StaticPrimarySensorHub([snapshot]),
            shell_executor=shell_executor,
        )
        action = Action(
            type=ActionType.SHELL_EXECUTE,
            target=TargetRef(),
            purpose="Inspect repository state.",
            reason="CLI is faster than GUI for this task.",
            preconditions=[],
            expected_outcome="The repository status is available for replanning.",
            shell_kind="cmd",
            shell_command="echo hello",
        )

        verification = toolset.verify_target(action, observation)
        execution = toolset.execute_action(action)
        postcheck = toolset.wait_for_expected_change(
            "shell-demo",
            action,
            observation,
            recent_actions=[],
            execution_result=execution,
        )
        validation = toolset.validate_outcome(
            action.expected_outcome,
            postcheck,
            previous_observation=observation,
            action=action,
        )

        self.assertTrue(verification.matched)
        self.assertEqual(shell_executor.actions[0].shell_command, "echo hello")
        self.assertEqual(builder.structured_calls, 1)
        self.assertEqual(postcheck.raw_ref["last_execution"]["payload"]["stdout"], "hello")
        self.assertEqual(postcheck.raw_ref["screenshot_count"], 0)
        self.assertTrue(validation.success)

    def _write_test_image(self, path: Path, color: QColor, accent_rect: tuple[int, int, int, int] | None = None) -> None:
        image = QImage(32, 32, QImage.Format_RGB32)
        image.fill(color)
        if accent_rect is not None:
            left, top, width, height = accent_rect
            accent = QColor(240, 240, 240)
            for y in range(top, min(top + height, image.height())):
                for x in range(left, min(left + width, image.width())):
                    image.setPixelColor(x, y, accent)
        image.save(str(path))

    def _make_windows_toolset(self) -> WindowsAgentToolset:
        return WindowsAgentToolset(
            root=self.temp_dir,
            observation_builder=DummyObservationBuilder(),
            window_manager=DummyWindowManager(),
            input_executor=DummyInputExecutor(),
            uia_adapter=DummyUIAAdapter(),
            live_planner=None,
        )

    def _observation(self, screenshot_path: str) -> Observation:
        return Observation(
            screenshot_path=screenshot_path,
            active_window=WindowInfo(window_id=1, title="Excel"),
            visible_windows=[WindowInfo(window_id=1, title="Excel")],
            detected_elements=[
                DetectedElement(
                    window_id=1,
                    name="Next",
                    control_type="button",
                    bounds=Bounds(100, 120, 120, 40),
                    confidence=0.9,
                )
            ],
            ui_tree_summary="Excel wizard page",
            cursor_position=(0, 0),
            focused_element="",
            textual_hints=["Excel"],
            recent_actions=[],
        )


if __name__ == "__main__":
    unittest.main()
