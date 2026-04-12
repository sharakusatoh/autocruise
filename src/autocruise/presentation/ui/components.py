from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from autocruise.presentation.ui.icons import icon_size
from autocruise.presentation.ui.tokens import COLORS, SPACE


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "section")
        layout.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("role", "muted")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        layout.addWidget(self.subtitle_label)

    def set_text(self, title: str, subtitle: str = "") -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))


class AppButton(QPushButton):
    def __init__(self, text: str, variant: str = "secondary", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("variant", variant)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setCursor(Qt.PointingHandCursor)


class AppLineEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setMinimumHeight(42)
        self.setTextMargins(12, 0, 12, 0)


class AppComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(42)
        self._sync_line_edit()

    def setEditable(self, editable: bool) -> None:  # noqa: N802
        super().setEditable(editable)
        self._sync_line_edit()

    def setCurrentText(self, text: str) -> None:  # noqa: N802
        for index in range(self.count()):
            if self.itemText(index) == text or self.itemData(index) == text:
                self.setCurrentIndex(index)
                if self.isEditable():
                    super().setCurrentText(self.itemText(index))
                return
        super().setCurrentText(text)

    def _sync_line_edit(self) -> None:
        editor = self.lineEdit()
        if editor is None:
            return
        editor.setAttribute(Qt.WA_InputMethodEnabled, True)
        editor.setFrame(False)
        editor.setTextMargins(0, 0, 0, 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(COLORS.text_secondary), 1.5))
        right = self.rect().right() - 16
        center_y = self.rect().center().y()
        painter.drawLine(right - 6, center_y - 2, right, center_y + 4)
        painter.drawLine(right, center_y + 4, right + 6, center_y - 2)


class SidebarItem(QPushButton):
    def __init__(self, text: str, icon, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setProperty("sidebarItem", True)
        self.setCheckable(True)
        self.setIcon(icon)
        self.setIconSize(icon_size())
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(f"    {text}" if text else "")


class StatusBadge(QLabel):
    TONES = {
        "ready": ("rgba(255,255,255,0.06)", COLORS.text_secondary),
        "running": ("rgba(16,163,127,0.18)", COLORS.accent),
        "paused": ("rgba(217,164,65,0.16)", COLORS.warning),
        "approval": ("rgba(217,164,65,0.16)", COLORS.warning),
        "error": ("rgba(232,93,117,0.16)", COLORS.danger),
        "done": ("rgba(16,163,127,0.18)", COLORS.accent),
    }

    def __init__(self, text: str = "", tone: str = "ready", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(12, 5, 12, 5)
        self.setMinimumHeight(30)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        background, foreground = self.TONES.get(tone, self.TONES["ready"])
        self.setStyleSheet(
            f"QLabel {{ background: {background}; color: {foreground}; border: 1px solid rgba(255,255,255,0.06); border-radius: 999px; padding: 6px 12px; font-size: 12px; font-weight: 600; }}"
        )


class EmptyState(QWidget):
    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.subtitle = subtitle
        self.setMinimumHeight(300)

    def set_copy(self, title: str, subtitle: str) -> None:
        self.title = title
        self.subtitle = subtitle
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS.card))
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        preview_rect = self.rect().adjusted(40, 36, -40, -92)
        painter.drawRoundedRect(preview_rect, 18, 18)
        inner = preview_rect.adjusted(20, 20, -20, -20)
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        painter.drawRoundedRect(inner, 12, 12)
        painter.drawLine(inner.left() + 24, inner.top() + 34, inner.right() - 24, inner.top() + 34)
        painter.drawLine(inner.left() + 24, inner.top() + 64, inner.right() - 40, inner.top() + 64)
        painter.drawLine(inner.left() + 24, inner.top() + 94, inner.right() - 72, inner.top() + 94)
        painter.setPen(QColor(COLORS.text_primary))
        painter.setFont(self.font())
        painter.drawText(self.rect().adjusted(0, 0, 0, -56), Qt.AlignHCenter | Qt.AlignBottom, self.title)
        painter.setPen(QColor(COLORS.text_secondary))
        painter.drawText(
            self.rect().adjusted(48, 0, -48, -24),
            Qt.AlignHCenter | Qt.AlignBottom | Qt.TextWordWrap,
            self.subtitle,
        )


class AppTextEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.viewport().setAttribute(Qt.WA_InputMethodEnabled, True)
        self.viewport().setAutoFillBackground(False)
        self.setFrameStyle(QFrame.NoFrame)
        self.document().setDocumentMargin(12)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            "QPlainTextEdit { border-radius: 14px; }"
            "QPlainTextEdit > QWidget { background: transparent; border-radius: 14px; }"
        )

    def inputMethodQuery(self, query):  # noqa: N802
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            rect = self.cursorRect()
            rect.translate(self.viewport().pos())
            return rect
        return super().inputMethodQuery(query)


class InputEditor(AppTextEditor):
    submitted = Signal()

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setMinimumHeight(132)


class ThinScrollBar(QScrollBar):
    def __init__(self, orientation: Qt.Orientation = Qt.Vertical, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._dragging = False
        self._drag_offset = 0
        if orientation == Qt.Vertical:
            self.setFixedWidth(8)

    def _thumb_rect(self):
        if self.orientation() != Qt.Vertical:
            return self.rect()
        groove = self.rect().adjusted(0, 4, 0, -4)
        span = max(0, self.maximum() - self.minimum())
        if span == 0:
            return groove
        total = span + max(1, self.pageStep())
        length = int(groove.height() * (self.pageStep() / total))
        length = max(44, min(120, length))
        track = max(1, groove.height() - length)
        ratio = (self.value() - self.minimum()) / span
        top = groove.top() + int(track * ratio)
        return groove.adjusted(0, top - groove.top(), 0, top - groove.top() - track)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        rect = self._thumb_rect()
        painter.setBrush(QColor(255, 255, 255, 58))
        painter.drawRoundedRect(rect, 4, 4)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        thumb = self._thumb_rect()
        if thumb.contains(event.position().toPoint()):
            self._dragging = True
            self._drag_offset = int(event.position().y()) - thumb.top()
            event.accept()
            return
        self._jump_to(event.position().y())
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging:
            return
        self._jump_to(int(event.position().y()) - self._drag_offset + self._thumb_rect().height() / 2)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _jump_to(self, y_pos: float) -> None:
        groove = self.rect().adjusted(0, 2, 0, -2)
        thumb = self._thumb_rect()
        track = max(1, groove.height() - thumb.height())
        ratio = min(1.0, max(0.0, (y_pos - groove.top() - thumb.height() / 2) / track))
        span = self.maximum() - self.minimum()
        self.setValue(self.minimum() + int(span * ratio))


class ListPanel(QListWidget):
    selected_payload = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSpacing(SPACE.xs)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBar(ThinScrollBar(Qt.Vertical, self))
        self.verticalScrollBar().setSingleStep(20)
        self.currentItemChanged.connect(self._emit_current)

    def replace_items(self, payloads: list[dict], factory) -> None:
        self.clear()
        available_width = max(160, self.viewport().width() - 14)
        for payload in payloads:
            item = QListWidgetItem()
            widget = factory(payload)
            widget.setFixedWidth(available_width)
            widget.adjustSize()
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.UserRole, payload)
            self.addItem(item)
            self.setItemWidget(item, widget)
        if self.count():
            self.setCurrentRow(0)
        self._sync_selection()

    def _emit_current(self, current, _previous) -> None:
        self._sync_selection()
        self.selected_payload.emit(current.data(Qt.UserRole) if current else None)

    def _sync_selection(self) -> None:
        for index in range(self.count()):
            item = self.item(index)
            widget = self.itemWidget(item)
            if widget is None:
                continue
            widget.setProperty("selected", index == self.currentRow())
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        available_width = max(160, self.viewport().width() - 14)
        for index in range(self.count()):
            item = self.item(index)
            widget = self.itemWidget(item)
            if widget is None:
                continue
            widget.setFixedWidth(available_width)
            widget.adjustSize()
            item.setSizeHint(widget.sizeHint())


class MetaLine(QWidget):
    def __init__(self, values: list[str], parent: QWidget | None = None, *, single_line: bool = False) -> None:
        super().__init__(parent)
        self._single_line = single_line
        self._full_text = "  /  ".join(value for value in values if value)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.label = QLabel(self._full_text)
        self.label.setProperty("role", "muted")
        self.label.setWordWrap(not single_line)
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def sizeHint(self) -> QSize:  # noqa: D401
        return QSize(self.width(), self.label.sizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._single_line:
            return
        self.label.setText(self.label.fontMetrics().elidedText(self._full_text, Qt.ElideRight, max(80, self.width())))


class ListCard(Card):
    def __init__(
        self,
        title: str,
        meta: list[str],
        parent: QWidget | None = None,
        *,
        single_line_title: bool = False,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setProperty("listItemCard", True)
        self.setProperty("selected", False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._single_line_title = single_line_title
        self._compact = compact
        self._full_title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8 if compact else 10, 6 if compact else 8, 8 if compact else 10, 6 if compact else 8)
        layout.setSpacing(4 if compact else 6)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "body")
        self.title_label.setWordWrap(not single_line_title)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if single_line_title:
            self.title_label.setMaximumHeight(self.title_label.fontMetrics().height() + 2)
        layout.addWidget(self.title_label)
        self.meta_line = MetaLine(meta, single_line=compact)
        layout.addWidget(self.meta_line)
        self.setMinimumHeight(54 if compact else (70 if single_line_title else 84))

    def sizeHint(self) -> QSize:  # noqa: D401
        margins = self.layout().contentsMargins()
        width = max(220, self.width() if self.width() > 0 else 280)
        inner_width = max(160, width - margins.left() - margins.right())
        self.title_label.setFixedWidth(inner_width)
        self._sync_title(inner_width)
        self.meta_line.label.setFixedWidth(inner_width)
        self.layout().activate()
        height = (
            margins.top()
            + self.title_label.sizeHint().height()
            + self.layout().spacing()
            + self.meta_line.label.sizeHint().height()
            + margins.bottom()
        )
        minimum_height = 54 if self._compact else (70 if self._single_line_title else 84)
        return QSize(width, max(minimum_height, height))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        margins = self.layout().contentsMargins()
        self._sync_title(max(160, self.width() - margins.left() - margins.right()))

    def _sync_title(self, width: int) -> None:
        if not self._single_line_title:
            self.title_label.setText(self._full_title)
            return
        self.title_label.setText(self.title_label.fontMetrics().elidedText(self._full_title, Qt.ElideRight, width))
