from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from autocruise.presentation.labels import tr
from autocruise.presentation.ui.components import AppButton, Card, ListCard, ListPanel, SectionHeader


class KnowledgePage(QWidget):
    detail_requested = Signal()
    create_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        left = Card()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(24, 24, 24, 24)
        left_layout.setSpacing(12)
        self.header = SectionHeader(tr("tab.knowledge"), tr("message.custom_prompt_subtitle"))
        left_layout.addWidget(self.header)
        self.new_button = AppButton(tr("button.new"), "secondary")
        left_layout.addWidget(self.new_button, 0, Qt.AlignLeft)
        self.list_panel = ListPanel()
        left_layout.addWidget(self.list_panel, 1)
        layout.addWidget(left, 6)

        right = Card()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(24, 24, 24, 24)
        right_layout.setSpacing(14)
        self.detail_header = SectionHeader(tr("label.knowledge_summary"), tr("message.no_selection"))
        right_layout.addWidget(self.detail_header)
        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "body")
        self.summary_label.setWordWrap(True)
        self.summary_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_layout.addWidget(self.summary_label)
        self.meta_label = QLabel("")
        self.meta_label.setProperty("role", "muted")
        self.meta_label.setWordWrap(True)
        right_layout.addWidget(self.meta_label)
        self.detail_button = AppButton(tr("button.details"), "secondary")
        right_layout.addWidget(self.detail_button, 0, Qt.AlignLeft)
        right_layout.addStretch(1)
        layout.addWidget(right, 4)

        self.detail_button.clicked.connect(self.detail_requested.emit)
        self.new_button.clicked.connect(self.create_requested.emit)

    def set_items(self, items_by_category: dict[str, list[dict]]) -> None:
        items = items_by_category.get("custom_prompt", [])

        def factory(payload: dict) -> QWidget:
            meta = [payload.get("updated_at", ""), payload.get("kind_label", "")]
            return ListCard(payload.get("name", ""), meta)

        self.list_panel.replace_items(items, factory)
        if not items:
            self.detail_header.set_text(tr("label.knowledge_summary"), tr("message.no_selection"))
            self.summary_label.setText("")
            self.meta_label.setText("")

    def show_item(self, summary: str, meta: str) -> None:
        self.detail_header.set_text(tr("label.knowledge_summary"))
        self.summary_label.setText(summary)
        self.meta_label.setText(meta)

    def retranslate(self) -> None:
        self.header.set_text(tr("tab.knowledge"), tr("message.custom_prompt_subtitle"))
        self.detail_header.set_text(tr("label.knowledge_summary"), tr("message.no_selection"))
        self.new_button.setText(tr("button.new"))
        self.detail_button.setText(tr("button.details"))
