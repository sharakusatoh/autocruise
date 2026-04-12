from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from autocruise.presentation.labels import tr
from autocruise.presentation.ui.components import AppButton, Card, InputEditor, SectionHeader, StatusBadge, ThinScrollBar


class HomePage(QWidget):
    run_requested = Signal(str)
    pause_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._running = False
        self._status_tone = "ready"
        self._activity_fallback = tr("message.home_empty")

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
        content_layout.setSpacing(16)

        self.goal_card = Card()
        goal_layout = QVBoxLayout(self.goal_card)
        goal_layout.setContentsMargins(20, 20, 20, 20)
        goal_layout.setSpacing(8)
        self.goal_header = SectionHeader(tr("label.current_goal"))
        goal_layout.addWidget(self.goal_header)
        self.goal_value = QLabel(tr("message.goal_idle"))
        self.goal_value.setProperty("role", "body")
        self.goal_value.setWordWrap(True)
        goal_layout.addWidget(self.goal_value)
        content_layout.addWidget(self.goal_card)

        self.status_card = Card()
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(20, 20, 20, 20)
        status_layout.setSpacing(10)
        self.status_header = SectionHeader(tr("label.current_state"))
        status_layout.addWidget(self.status_header)
        badge_row = QHBoxLayout()
        badge_row.setSpacing(12)
        self.status_badge = StatusBadge(tr("status.ready"), tone="ready")
        badge_row.addWidget(self.status_badge, 0, Qt.AlignLeft)
        badge_row.addStretch(1)
        status_layout.addLayout(badge_row)
        self.activity_label = QLabel(tr("message.home_empty"))
        self.activity_label.setProperty("role", "body")
        self.activity_label.setWordWrap(True)
        status_layout.addWidget(self.activity_label)
        self.connection_hint = QLabel("")
        self.connection_hint.setProperty("role", "muted")
        self.connection_hint.setWordWrap(True)
        self.connection_hint.hide()
        status_layout.addWidget(self.connection_hint)
        self.background_hint = QLabel(tr("message.background_mode"))
        self.background_hint.setProperty("role", "muted")
        self.background_hint.setWordWrap(True)
        status_layout.addWidget(self.background_hint)
        content_layout.addWidget(self.status_card)

        self.input_card = Card()
        input_layout = QVBoxLayout(self.input_card)
        input_layout.setContentsMargins(20, 20, 20, 20)
        input_layout.setSpacing(12)
        self.input_header = SectionHeader(tr("label.goal"), tr("label.prompt_hint"))
        input_layout.addWidget(self.input_header)
        self.goal_input = InputEditor("")
        self.goal_input.setMaximumHeight(132)
        input_layout.addWidget(self.goal_input)
        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.run_button = AppButton(tr("button.run"), "primary")
        input_row.addWidget(self.run_button)
        input_row.addStretch(1)
        input_layout.addLayout(input_row)
        content_layout.addWidget(self.input_card)

        self.controls_card = Card()
        controls_layout = QHBoxLayout(self.controls_card)
        controls_layout.setContentsMargins(20, 16, 20, 16)
        controls_layout.setSpacing(10)
        self.pause_button = AppButton(tr("button.pause"), "secondary")
        self.stop_button = AppButton(tr("button.stop"), "danger")
        controls_layout.addWidget(self.pause_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addStretch(1)
        content_layout.addWidget(self.controls_card)
        content_layout.addStretch(1)

        self.goal_input.textChanged.connect(self._sync_goal_preview)
        self.run_button.clicked.connect(self._emit_run)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)

        self._sync_goal_preview()
        self.set_running(False)

    def _sync_goal_preview(self) -> None:
        if self._running:
            return
        draft = self.goal_input.toPlainText().strip()
        self.goal_value.setText(draft or tr("message.goal_idle"))

    def _emit_run(self) -> None:
        self.run_requested.emit(self.goal_input.toPlainText().strip())

    def set_goal(self, text: str) -> None:
        self.goal_value.setText(text or tr("message.goal_idle"))

    def set_preview(self, path: str) -> None:
        _ = path

    def set_status(self, badge: str, tone: str, hint: str, connection: str) -> None:
        self._status_tone = tone
        self._activity_fallback = hint or tr("message.home_empty")
        self.status_badge.setText(badge)
        self.status_badge.set_tone(tone)
        if tone == "ready":
            self.activity_label.setText("")
            self.activity_label.hide()
        else:
            self.activity_label.setText(self._activity_fallback)
            self.activity_label.show()
        self.connection_hint.setText(connection)
        self.connection_hint.setVisible(bool(connection))

    def set_next_action(self, text: str) -> None:
        if self._status_tone == "ready":
            self.activity_label.setText("")
            self.activity_label.hide()
            return
        next_text = text or self._activity_fallback
        self.activity_label.setText(next_text)
        self.activity_label.setVisible(bool(next_text))

    def set_running(self, running: bool) -> None:
        self._running = running
        self.run_button.setEnabled(not running)
        self.pause_button.setEnabled(running)
        self.stop_button.setEnabled(running)
        if not running:
            self._sync_goal_preview()

    def set_pause_label(self, text: str) -> None:
        self.pause_button.setText(text)

    def set_stop_label(self, text: str) -> None:
        self.stop_button.setText(text)

    def retranslate(self) -> None:
        self.goal_header.set_text(tr("label.current_goal"))
        self.status_header.set_text(tr("label.current_state"))
        self.input_header.set_text(tr("label.goal"), tr("label.prompt_hint"))
        self.background_hint.setText(tr("message.background_mode"))
        self.goal_input.setPlaceholderText("")
        self.run_button.setText(tr("button.run"))
        self.pause_button.setText(tr("button.pause"))
        self.stop_button.setText(tr("button.stop"))
        if not self._running:
            self.goal_value.setText(self.goal_input.toPlainText().strip() or tr("message.goal_idle"))
