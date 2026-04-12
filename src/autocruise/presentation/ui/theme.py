from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from autocruise.presentation.ui.tokens import COLORS, RADII


def apply_theme(app: QApplication) -> None:
    font = QFont()
    font.setPointSize(10)
    font.setFamilies(["Segoe UI", "Inter", "Arial", "Yu Gothic UI"])
    app.setFont(font)
    app.setStyleSheet(build_stylesheet())


def build_stylesheet() -> str:
    return f"""
    QWidget {{
        background: {COLORS.background};
        color: {COLORS.text_primary};
        selection-background-color: {COLORS.accent};
        selection-color: {COLORS.text_primary};
    }}
    QMainWindow, QWidget#Root {{
        background: {COLORS.background};
    }}
    QFrame[card="true"] {{
        background: {COLORS.card};
        border: 1px solid {COLORS.border};
        border-radius: {RADII.card}px;
    }}
    QFrame[listItemCard="true"][selected="true"] {{
        background: {COLORS.card_hover};
        border: 1px solid rgba(16,163,127,0.24);
    }}
    QFrame[sidebar="true"] {{
        background: {COLORS.background};
        border: 1px solid transparent;
        border-radius: {RADII.card}px;
    }}
    QLabel[role="title"] {{
        color: {COLORS.text_primary};
        font-size: 24px;
        font-weight: 700;
        background: transparent;
    }}
    QLabel[role="brand"] {{
        color: {COLORS.text_primary};
        font-size: 19px;
        font-weight: 400;
        background: transparent;
        letter-spacing: 0.2px;
    }}
    QLabel[role="subtitle"] {{
        color: {COLORS.text_secondary};
        font-size: 12px;
        background: transparent;
    }}
    QLabel[role="section"] {{
        color: {COLORS.text_primary};
        font-size: 14px;
        font-weight: 600;
        background: transparent;
    }}
    QLabel[role="body"] {{
        color: {COLORS.text_primary};
        font-size: 13px;
        background: transparent;
    }}
    QLabel[role="muted"] {{
        color: {COLORS.text_secondary};
        font-size: 12px;
        background: transparent;
    }}
    QLineEdit, QPlainTextEdit {{
        background: {COLORS.input};
        border: 1px solid {COLORS.border};
        border-radius: {RADII.input}px;
        padding: 0px;
        color: {COLORS.text_primary};
        selection-background-color: rgba(16,163,127,0.25);
    }}
    QLineEdit:focus, QPlainTextEdit:focus {{
        background: {COLORS.input_focus};
        border: 1px solid rgba(16,163,127,0.55);
    }}
    QComboBox QLineEdit {{
        background: transparent;
        border: 0;
        padding: 0px;
        margin: 0px;
    }}
    QPushButton {{
        border: 0;
        border-radius: {RADII.button}px;
        padding: 11px 16px;
        min-height: 18px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton[variant="primary"] {{
        background: {COLORS.accent};
        color: #08110E;
    }}
    QPushButton[variant="primary"]:hover {{
        background: {COLORS.accent_hover};
    }}
    QPushButton[variant="primary"]:pressed {{
        background: {COLORS.accent_pressed};
    }}
    QPushButton[variant="secondary"] {{
        background: rgba(255,255,255,0.04);
        color: {COLORS.text_primary};
    }}
    QPushButton[variant="secondary"]:hover {{
        background: rgba(255,255,255,0.08);
    }}
    QPushButton[variant="secondary"]:pressed {{
        background: rgba(255,255,255,0.12);
    }}
    QPushButton[variant="ghost"] {{
        background: transparent;
        color: {COLORS.text_secondary};
    }}
    QPushButton[variant="ghost"]:hover {{
        background: rgba(255,255,255,0.05);
        color: {COLORS.text_primary};
    }}
    QPushButton[variant="danger"] {{
        background: rgba(232,93,117,0.16);
        color: {COLORS.danger};
    }}
    QPushButton[variant="danger"]:hover {{
        background: rgba(232,93,117,0.22);
    }}
    QPushButton[variant="danger"]:pressed {{
        background: rgba(232,93,117,0.30);
    }}
    QPushButton:disabled {{
        background: rgba(255,255,255,0.05);
        color: {COLORS.text_tertiary};
    }}
    QPushButton[sidebarItem="true"] {{
        text-align: left;
        padding: 12px 14px;
        border-radius: 14px;
        background: transparent;
        color: {COLORS.text_secondary};
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton[sidebarItem="true"]:hover {{
        background: rgba(255,255,255,0.04);
        color: {COLORS.text_primary};
    }}
    QPushButton[sidebarItem="true"]:checked {{
        background: rgba(16,163,127,0.12);
        color: {COLORS.text_primary};
        border: 1px solid rgba(16,163,127,0.24);
    }}
    QPushButton[chip="true"] {{
        border-radius: 12px;
        padding: 8px 12px;
        background: rgba(255,255,255,0.04);
        color: {COLORS.text_secondary};
    }}
    QPushButton[chip="true"]:checked {{
        background: rgba(16,163,127,0.16);
        color: {COLORS.text_primary};
    }}
    QListWidget {{
        background: transparent;
        border: 0;
        outline: none;
    }}
    QListWidget::item {{
        border: 0;
        padding: 0px;
        margin: 0px 0px 8px 0px;
    }}
    QListWidget::item:selected {{
        background: transparent;
    }}
    QSplitter::handle {{
        background: transparent;
    }}
    QSplitter::handle:horizontal {{
        width: 8px;
    }}
    QSplitter::handle:horizontal:hover {{
        background: rgba(255,255,255,0.03);
    }}
    QScrollArea {{
        background: transparent;
        border: 0;
    }}
    QMenu {{
        background: {COLORS.card};
        border: 1px solid {COLORS.border};
        border-radius: {RADII.input}px;
        padding: 8px;
    }}
    QMenu::item {{
        padding: 8px 12px;
        border-radius: 10px;
        margin: 2px 0;
    }}
    QMenu::item:selected {{
        background: {COLORS.card_hover};
    }}
    QMenu::separator {{
        height: 1px;
        background: {COLORS.border};
        margin: 8px 4px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 4px 0 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,0.18);
        border-radius: 4px;
        min-height: 28px;
        max-height: 72px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 0px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: transparent;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QComboBox {{
        background: {COLORS.input};
        border: 1px solid {COLORS.border};
        border-radius: {RADII.input}px;
        padding: 10px 32px 10px 12px;
        min-height: 18px;
    }}
    QComboBox:hover {{
        background: {COLORS.input_focus};
    }}
    QComboBox::drop-down {{
        width: 28px;
        border: 0;
    }}
    QComboBox::down-arrow {{
        image: none;
        width: 0px;
        height: 0px;
    }}
    QComboBox QAbstractItemView {{
        background: {COLORS.card};
        border: 1px solid {COLORS.border};
        selection-background-color: rgba(16,163,127,0.18);
        padding: 6px;
    }}
    QCheckBox {{
        spacing: 8px;
        color: {COLORS.text_primary};
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 9px;
        border: 1px solid {COLORS.border};
        background: rgba(255,255,255,0.03);
    }}
    QCheckBox::indicator:checked {{
        background: {COLORS.accent};
        border: 1px solid rgba(16,163,127,0.55);
    }}
    """
