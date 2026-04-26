from __future__ import annotations

from PySide6.QtCore import QDateTime, Qt, Signal, QTime
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QDateTimeEdit, QGridLayout, QLabel, QTimeEdit, QVBoxLayout, QWidget

from autocruise.presentation.labels import tr
from autocruise.presentation.ui.components import (
    AppButton,
    AppComboBox,
    AppLineEdit,
    Card,
    InputEditor,
    ListCard,
    ListPanel,
    SectionHeader,
    StatusBadge,
)


class SchedulesPage(QWidget):
    new_requested = Signal()
    save_requested = Signal(dict)
    enable_requested = Signal(str)
    disable_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_task_id = ""

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(24)
        layout.setVerticalSpacing(0)

        left = Card()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(24, 24, 24, 24)
        left_layout.setSpacing(16)
        self.list_header = SectionHeader(tr("schedule.title"), tr("schedule.subtitle"))
        left_layout.addWidget(self.list_header)
        self.new_button = AppButton(tr("schedule.new"), "primary")
        left_layout.addWidget(self.new_button, 0, Qt.AlignLeft)
        self.list_panel = ListPanel()
        left_layout.addWidget(self.list_panel, 1)
        layout.addWidget(left, 0, 0, 1, 5)

        right = Card()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(24, 24, 24, 24)
        right_layout.setSpacing(16)
        self.editor_header = SectionHeader(tr("schedule.editor_title"), tr("schedule.editor_subtitle"))
        right_layout.addWidget(self.editor_header)

        meta_row = QGridLayout()
        meta_row.setHorizontalSpacing(12)
        meta_row.setVerticalSpacing(12)
        self.status_badge = StatusBadge(tr("schedule.state.scheduled"), "ready")
        meta_row.addWidget(self.status_badge, 0, 0, 1, 2, Qt.AlignLeft)
        self.last_result_label = QLabel("")
        self.last_result_label.setProperty("role", "muted")
        self.last_result_label.setWordWrap(True)
        meta_row.addWidget(self.last_result_label, 1, 0, 1, 2)
        right_layout.addLayout(meta_row)

        self.instruction_header = SectionHeader(tr("label.goal"))
        right_layout.addWidget(self.instruction_header)
        self.instruction_input = InputEditor("")
        self.instruction_input.setMaximumHeight(140)
        right_layout.addWidget(self.instruction_input)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)

        self.recurrence_label = QLabel(tr("schedule.recurrence"))
        self.recurrence_label.setProperty("role", "body")
        self.recurrence_combo = AppComboBox()
        self._set_combo_texts()
        form.addWidget(self.recurrence_label, 0, 0)
        form.addWidget(self.recurrence_combo, 0, 1)

        self.date_label = QLabel(tr("schedule.date_time"))
        self.date_label.setProperty("role", "body")
        self.date_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        form.addWidget(self.date_label, 1, 0)
        form.addWidget(self.date_edit, 1, 1)

        self.time_label = QLabel(tr("schedule.time"))
        self.time_label.setProperty("role", "body")
        self.time_edit = QTimeEdit(QTime.currentTime())
        self.time_edit.setDisplayFormat("HH:mm")
        form.addWidget(self.time_label, 2, 0)
        form.addWidget(self.time_edit, 2, 1)

        self.weekday_label = QLabel(tr("schedule.weekday"))
        self.weekday_label.setProperty("role", "body")
        self.weekday_combo = AppComboBox()
        self._set_weekday_texts()
        form.addWidget(self.weekday_label, 3, 0)
        form.addWidget(self.weekday_combo, 3, 1)

        self.interval_label = QLabel(tr("schedule.interval"))
        self.interval_label.setProperty("role", "body")
        self.interval_panel = QWidget()
        self.interval_panel.setAttribute(Qt.WA_StyledBackground, False)
        self.interval_panel.setStyleSheet("background: transparent;")
        self.interval_layout = QGridLayout(self.interval_panel)
        self.interval_layout.setContentsMargins(0, 0, 0, 0)
        self.interval_layout.setHorizontalSpacing(8)
        self.interval_hours_edit = AppLineEdit()
        self.interval_hours_edit.setValidator(QIntValidator(0, 999, self.interval_hours_edit))
        self.interval_hours_edit.setMaximumWidth(120)
        self.interval_hours_label = QLabel(tr("schedule.interval_hours"))
        self.interval_minutes_edit = AppLineEdit()
        self.interval_minutes_edit.setValidator(QIntValidator(0, 59, self.interval_minutes_edit))
        self.interval_minutes_edit.setMaximumWidth(120)
        self.interval_minutes_label = QLabel(tr("schedule.interval_minutes"))
        self.interval_layout.addWidget(self.interval_hours_edit, 0, 0)
        self.interval_layout.addWidget(self.interval_hours_label, 0, 1)
        self.interval_layout.addWidget(self.interval_minutes_edit, 0, 2)
        self.interval_layout.addWidget(self.interval_minutes_label, 0, 3)
        form.addWidget(self.interval_label, 4, 0)
        form.addWidget(self.interval_panel, 4, 1)

        self.random_runs_label = QLabel(tr("schedule.random_runs_per_day"))
        self.random_runs_label.setProperty("role", "body")
        self.random_runs_edit = AppLineEdit()
        self.random_runs_edit.setValidator(QIntValidator(1, 1440, self.random_runs_edit))
        self.random_runs_edit.setMaximumWidth(120)
        form.addWidget(self.random_runs_label, 5, 0)
        form.addWidget(self.random_runs_edit, 5, 1)
        right_layout.addLayout(form)

        actions = QGridLayout()
        actions.setHorizontalSpacing(10)
        actions.setVerticalSpacing(10)
        self.save_button = AppButton(tr("button.save"), "primary")
        self.enable_button = AppButton(tr("schedule.enable"), "secondary")
        self.disable_button = AppButton(tr("schedule.disable"), "secondary")
        self.delete_button = AppButton(tr("schedule.delete"), "danger")
        actions.addWidget(self.save_button, 0, 0)
        actions.addWidget(self.enable_button, 0, 1)
        actions.addWidget(self.disable_button, 1, 0)
        actions.addWidget(self.delete_button, 1, 1)
        right_layout.addLayout(actions)
        right_layout.addStretch(1)
        layout.addWidget(right, 0, 5, 1, 4)

        self.list_panel.selected_payload.connect(self._load_payload)
        self.new_button.clicked.connect(self.new_requested.emit)
        self.save_button.clicked.connect(self._emit_save)
        self.enable_button.clicked.connect(lambda: self.enable_requested.emit(self.current_task_id))
        self.disable_button.clicked.connect(lambda: self.disable_requested.emit(self.current_task_id))
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.current_task_id))
        self.recurrence_combo.currentIndexChanged.connect(self._sync_mode)

        self.clear_form()

    def set_jobs(self, items: list[dict]) -> None:
        def factory(payload: dict) -> QWidget:
            return ListCard(payload.get("name", ""), [payload.get("summary", ""), payload.get("result", "")])

        self.list_panel.replace_items(items, factory)
        if not items:
            self.clear_form()

    def clear_form(self) -> None:
        self.current_task_id = ""
        self.status_badge.setText(tr("schedule.state.scheduled"))
        self.status_badge.set_tone("ready")
        self.last_result_label.setText(tr("schedule.empty"))
        self.instruction_input.setPlainText("")
        self.recurrence_combo.setCurrentIndex(0)
        self.date_edit.setDateTime(QDateTime.currentDateTime())
        self.time_edit.setTime(QTime.currentTime())
        self.weekday_combo.setCurrentIndex(0)
        self.interval_hours_edit.setText("0")
        self.interval_minutes_edit.setText("10")
        self.random_runs_edit.setText("10")
        self._sync_mode()
        self._sync_action_buttons(False, False)

    def load_job(self, payload: dict) -> None:
        self.current_task_id = payload.get("task_id", "")
        self.instruction_input.setPlainText(payload.get("instruction", ""))
        self._set_combo(self.recurrence_combo, payload.get("recurrence", "once"))
        if payload.get("run_at"):
            self.date_edit.setDateTime(QDateTime.fromString(payload["run_at"], Qt.ISODate))
        if payload.get("run_time"):
            self.time_edit.setTime(QTime.fromString(payload["run_time"], "HH:mm"))
        self._set_combo(self.weekday_combo, payload.get("weekday", "Monday"))
        interval_minutes = int(payload.get("interval_minutes", 0) or 0)
        self.interval_hours_edit.setText(str(interval_minutes // 60))
        self.interval_minutes_edit.setText(str(interval_minutes % 60))
        self.random_runs_edit.setText(str(int(payload.get("random_runs_per_day", 10) or 10)))
        self.status_badge.setText(payload.get("state_label", tr("schedule.state.scheduled")))
        self.status_badge.set_tone(payload.get("tone", "ready"))
        self.last_result_label.setText(payload.get("last_result_text", tr("schedule.empty")))
        self._sync_mode()
        self._sync_action_buttons(True, payload.get("enabled", False))

    def retranslate(self) -> None:
        current_recurrence = self.recurrence_combo.currentData() or "once"
        current_weekday = self.weekday_combo.currentData() or "Monday"
        self.list_header.set_text(tr("schedule.title"), tr("schedule.subtitle"))
        self.new_button.setText(tr("schedule.new"))
        self.editor_header.set_text(tr("schedule.editor_title"), tr("schedule.editor_subtitle"))
        self.instruction_header.set_text(tr("label.goal"))
        self.recurrence_label.setText(tr("schedule.recurrence"))
        self.date_label.setText(tr("schedule.date_time"))
        self.time_label.setText(tr("schedule.time"))
        self.weekday_label.setText(tr("schedule.weekday"))
        self.interval_label.setText(tr("schedule.interval"))
        self.interval_hours_label.setText(tr("schedule.interval_hours"))
        self.interval_minutes_label.setText(tr("schedule.interval_minutes"))
        self.random_runs_label.setText(tr("schedule.random_runs_per_day"))
        self._set_combo_texts(current_recurrence)
        self._set_weekday_texts(current_weekday)
        self.save_button.setText(tr("button.save"))
        self.enable_button.setText(tr("schedule.enable"))
        self.disable_button.setText(tr("schedule.disable"))
        self.delete_button.setText(tr("schedule.delete"))
        if not self.current_task_id:
            self.status_badge.setText(tr("schedule.state.scheduled"))
            self.last_result_label.setText(tr("schedule.empty"))
        self._sync_mode()

    def _set_combo_texts(self, current: str | None = None) -> None:
        items = [
            (tr("schedule.once"), "once"),
            (tr("schedule.daily"), "daily"),
            (tr("schedule.weekdays"), "weekdays"),
            (tr("schedule.weekly"), "weekly"),
            (tr("schedule.interval"), "interval"),
            (tr("schedule.random_hourly"), "random_hourly"),
            (tr("schedule.random_daily"), "random_daily"),
        ]
        selected = current or self.recurrence_combo.currentData() or "once"
        self.recurrence_combo.clear()
        for label, value in items:
            self.recurrence_combo.addItem(label, value)
        self._set_combo(self.recurrence_combo, selected)

    def _set_weekday_texts(self, current: str | None = None) -> None:
        selected = current or self.weekday_combo.currentData() or "Monday"
        self.weekday_combo.clear()
        for label, value in (
            (tr("weekday.monday"), "Monday"),
            (tr("weekday.tuesday"), "Tuesday"),
            (tr("weekday.wednesday"), "Wednesday"),
            (tr("weekday.thursday"), "Thursday"),
            (tr("weekday.friday"), "Friday"),
            (tr("weekday.saturday"), "Saturday"),
            (tr("weekday.sunday"), "Sunday"),
        ):
            self.weekday_combo.addItem(label, value)
        self._set_combo(self.weekday_combo, selected)

    def _set_combo(self, combo: AppComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def _sync_mode(self) -> None:
        recurrence = self.recurrence_combo.currentData() or "once"
        is_once = recurrence == "once"
        is_weekly = recurrence == "weekly"
        is_fixed_time = recurrence in {"daily", "weekdays", "weekly"}
        is_interval = recurrence == "interval"
        is_random_daily = recurrence == "random_daily"
        self.date_label.setVisible(is_once)
        self.date_edit.setVisible(is_once)
        self.time_label.setVisible(is_fixed_time)
        self.time_edit.setVisible(is_fixed_time)
        self.weekday_label.setVisible(is_weekly)
        self.weekday_combo.setVisible(is_weekly)
        self.interval_label.setVisible(is_interval)
        self.interval_panel.setVisible(is_interval)
        self.random_runs_label.setVisible(is_random_daily)
        self.random_runs_edit.setVisible(is_random_daily)

    def _sync_action_buttons(self, has_selection: bool, enabled: bool) -> None:
        self.enable_button.setVisible(not has_selection or not enabled)
        self.disable_button.setVisible(has_selection and enabled)
        self.enable_button.setEnabled(has_selection and not enabled)
        self.disable_button.setEnabled(has_selection and enabled)
        self.delete_button.setEnabled(has_selection)

    def _load_payload(self, payload: dict | None) -> None:
        if not payload:
            return
        self.load_job(payload)

    def _emit_save(self) -> None:
        recurrence = self.recurrence_combo.currentData() or "once"
        hours = int(self.interval_hours_edit.text() or "0")
        minutes = int(self.interval_minutes_edit.text() or "0")
        payload = {
            "task_id": self.current_task_id,
            "instruction": self.instruction_input.toPlainText().strip(),
            "recurrence": recurrence,
            "run_at": self.date_edit.dateTime().toPython().isoformat(timespec="minutes")
            if recurrence == "once"
            else self.time_edit.time().toString("HH:mm"),
            "weekday": self.weekday_combo.currentData() or "Monday",
            "interval_minutes": max(1, hours * 60 + minutes),
            "random_runs_per_day": max(1, int(self.random_runs_edit.text() or "10")),
        }
        self.save_requested.emit(payload)
