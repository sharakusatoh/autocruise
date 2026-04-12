from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QScrollArea, QVBoxLayout, QWidget

from autocruise.presentation.labels import tr
from autocruise.presentation.ui.components import AppButton, Card, EmptyState, SectionHeader, ThinScrollBar


class HistoryPage(QWidget):
    diagnostics_requested = Signal()
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview: QPixmap | None = None

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

        self.detail_card = Card()
        detail_layout = QVBoxLayout(self.detail_card)
        detail_layout.setContentsMargins(24, 24, 24, 24)
        detail_layout.setSpacing(16)
        self.detail_header = SectionHeader(tr("label.history_summary"), tr("message.no_history"))
        detail_layout.addWidget(self.detail_header)

        self.detail_text = QLabel("")
        self.detail_text.setProperty("role", "body")
        self.detail_text.setWordWrap(True)
        self.detail_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(self.detail_text)

        self.capture_header = SectionHeader(tr("label.saved_captures"))
        detail_layout.addWidget(self.capture_header)

        self.capture_list = QListWidget()
        self.capture_list.setMaximumHeight(120)
        self.capture_list.currentTextChanged.connect(self._load_capture)
        detail_layout.addWidget(self.capture_list)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(260)
        self.preview.setStyleSheet("QLabel { background: transparent; }")
        self.preview_empty = EmptyState(tr("empty.session_title"), tr("empty.session_subtitle"))
        detail_layout.addWidget(self.preview_empty)
        detail_layout.addWidget(self.preview)
        self.preview.hide()

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.diagnostics_button = AppButton(tr("button.details"), "secondary")
        self.delete_button = AppButton(tr("button.delete_thread"), "danger")
        actions.addWidget(self.diagnostics_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        detail_layout.addLayout(actions)
        content_layout.addWidget(self.detail_card, 1)
        content_layout.addStretch(1)

        self.diagnostics_button.clicked.connect(self.diagnostics_requested.emit)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.clear_detail()

    def set_records(self, records: list[dict]) -> None:
        if not records:
            self.clear_detail()
            return
        if not self.diagnostics_button.isEnabled():
            self.detail_header.set_text(tr("label.history_summary"), tr("message.no_selection"))

    def clear_detail(self) -> None:
        self.detail_header.set_text(tr("label.history_summary"), tr("message.no_history"))
        self.detail_text.setText("")
        self.capture_list.clear()
        self.capture_header.hide()
        self.capture_list.hide()
        self.preview_empty.show()
        self.preview.hide()
        self.diagnostics_button.setEnabled(False)
        self.delete_button.setEnabled(False)

    def show_detail(self, summary: str, detail_text: str, captures: list[str]) -> None:
        self.detail_header.set_text(tr("label.history_summary"), summary)
        self.detail_text.setText(detail_text)
        self.capture_list.clear()
        self.capture_list.addItems(captures)
        has_captures = bool(captures)
        self.capture_header.setVisible(has_captures)
        self.capture_list.setVisible(has_captures)
        if captures:
            self.capture_list.setCurrentRow(0)
        else:
            self.preview_empty.show()
            self.preview.hide()
        self.diagnostics_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def _load_capture(self, value: str) -> None:
        if not value:
            self.preview_empty.show()
            self.preview.hide()
            return
        pixmap = QPixmap(value)
        if pixmap.isNull():
            self.preview_empty.show()
            self.preview.hide()
            return
        self._preview = pixmap
        self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.preview.show()
        self.preview_empty.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._preview is not None and not self._preview.isNull():
            self.preview.setPixmap(self._preview.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def retranslate(self) -> None:
        self.capture_header.set_text(tr("label.saved_captures"))
        self.preview_empty.set_copy(tr("empty.session_title"), tr("empty.session_subtitle"))
        self.diagnostics_button.setText(tr("button.details"))
        self.delete_button.setText(tr("button.delete_thread"))
