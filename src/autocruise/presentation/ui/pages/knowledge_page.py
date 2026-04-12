from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from autocruise.presentation.labels import tr
from autocruise.presentation.ui.components import AppButton, Card, ListCard, ListPanel, SectionHeader


class KnowledgePage(QWidget):
    detail_requested = Signal()
    create_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_category = "app_knowledge"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        left = Card()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(24, 24, 24, 24)
        left_layout.setSpacing(16)
        self.header = SectionHeader(tr("tab.knowledge"))
        left_layout.addWidget(self.header)
        chips = QGridLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setHorizontalSpacing(8)
        chips.setVerticalSpacing(8)
        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(True)
        self.category_buttons: dict[str, AppButton] = {}
        for index, category in enumerate(("app_knowledge", "action_templates", "learning_history", "custom_prompt")):
            button = AppButton(tr(f"category.{category}"), "ghost")
            button.setProperty("chip", True)
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if category == self.current_category:
                button.setChecked(True)
            self.category_group.addButton(button)
            self.category_buttons[category] = button
            chips.addWidget(button, index // 2, index % 2)
            button.clicked.connect(lambda _checked=False, value=category: self._set_category(value))
        left_layout.addLayout(chips)
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
        self.new_button.clicked.connect(lambda: self.create_requested.emit(self.current_category))
        self._sync_create_button()

    def _set_category(self, category: str) -> None:
        self.current_category = category
        self._sync_create_button()

    def set_items(self, items_by_category: dict[str, list[dict]]) -> None:
        items = items_by_category.get(self.current_category, [])

        def factory(payload: dict) -> QWidget:
            meta = [payload.get("target", ""), payload.get("updated_at", ""), payload.get("kind_label", "")]
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
        self.header.set_text(tr("tab.knowledge"))
        self.detail_header.set_text(tr("label.knowledge_summary"), tr("message.no_selection"))
        for category, button in self.category_buttons.items():
            button.setText(tr(f"category.{category}"))
        self.new_button.setText(tr("button.new"))
        self.detail_button.setText(tr("button.details"))
        self._sync_create_button()

    def _sync_create_button(self) -> None:
        self.new_button.setVisible(self.current_category in {"app_knowledge", "action_templates", "custom_prompt"})
