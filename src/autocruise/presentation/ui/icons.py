from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def app_icon(size: int = 64, color: str = "#10A37F") -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    outer = QRectF(4, 4, size - 8, size - 8)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#171B22"))
    painter.drawRoundedRect(outer, 18, 18)
    inner = outer.adjusted(10, 10, -10, -10)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(inner, 14, 14)
    path = QPainterPath()
    path.moveTo(inner.left() + 10, inner.center().y())
    path.lineTo(inner.center().x(), inner.top() + 10)
    path.lineTo(inner.right() - 10, inner.center().y())
    path.lineTo(inner.center().x(), inner.bottom() - 10)
    path.closeSubpath()
    painter.setBrush(QColor("#08110E"))
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def nav_icon(name: str, color: str, size: int = 18) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    rect = QRectF(2.0, 2.0, size - 4.0, size - 4.0)

    if name == "home":
        path = QPainterPath()
        path.moveTo(rect.center().x(), rect.top())
        path.lineTo(rect.right(), rect.center().y() - 1)
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.center().y() - 1)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "history":
        painter.drawEllipse(rect)
        painter.drawLine(rect.center(), QPointF(rect.center().x(), rect.top() + 3))
        painter.drawLine(rect.center(), QPointF(rect.right() - 3, rect.center().y()))
    elif name == "knowledge":
        painter.drawRoundedRect(rect, 2, 2)
        painter.drawLine(rect.left() + 4, rect.top() + 5, rect.right() - 4, rect.top() + 5)
        painter.drawLine(rect.left() + 4, rect.top() + 9, rect.right() - 6, rect.top() + 9)
        painter.drawLine(rect.left() + 4, rect.top() + 13, rect.right() - 8, rect.top() + 13)
    elif name == "calendar":
        painter.drawRoundedRect(rect, 3, 3)
        painter.drawLine(rect.left() + 3, rect.top() + 6, rect.right() - 3, rect.top() + 6)
        painter.drawLine(rect.left() + 5, rect.top() - 0.5, rect.left() + 5, rect.top() + 4)
        painter.drawLine(rect.right() - 5, rect.top() - 0.5, rect.right() - 5, rect.top() + 4)
        painter.drawLine(rect.left() + 5, rect.center().y() + 1, rect.right() - 5, rect.center().y() + 1)
        painter.drawLine(rect.center().x(), rect.top() + 8, rect.center().x(), rect.bottom() - 4)
    elif name == "settings":
        outer = rect.adjusted(3.6, 3.6, -3.6, -3.6)
        inner = rect.adjusted(6.8, 6.8, -6.8, -6.8)
        for dx, dy in ((0, -6), (4.2, -4.2), (6, 0), (4.2, 4.2), (0, 6), (-4.2, 4.2), (-6, 0), (-4.2, -4.2)):
            start = rect.center() + QPointF(dx * 0.58, dy * 0.58)
            end = rect.center() + QPointF(dx, dy)
            painter.drawLine(start, end)
        painter.drawEllipse(outer)
        painter.drawEllipse(inner)
    elif name == "spark":
        path = QPainterPath()
        path.moveTo(rect.center().x(), rect.top())
        path.lineTo(rect.center().x() + 2.5, rect.center().y() - 1.5)
        path.lineTo(rect.right(), rect.center().y())
        path.lineTo(rect.center().x() + 2.5, rect.center().y() + 1.5)
        path.lineTo(rect.center().x(), rect.bottom())
        path.lineTo(rect.center().x() - 2.5, rect.center().y() + 1.5)
        path.lineTo(rect.left(), rect.center().y())
        path.lineTo(rect.center().x() - 2.5, rect.center().y() - 1.5)
        path.closeSubpath()
        painter.drawPath(path)
    else:
        painter.drawRoundedRect(rect, 4, 4)

    painter.end()
    return QIcon(pixmap)


def icon_size() -> QSize:
    return QSize(18, 18)
