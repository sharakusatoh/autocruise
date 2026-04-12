from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColorTokens:
    background: str = "#0E1116"
    sidebar: str = "#11151B"
    card: str = "#171B22"
    card_hover: str = "#1D232C"
    input: str = "#151A21"
    input_focus: str = "#1B212A"
    border: str = "rgba(255,255,255,0.08)"
    text_primary: str = "#ECEFF4"
    text_secondary: str = "#A7B0BE"
    text_tertiary: str = "#7C8797"
    accent: str = "#10A37F"
    accent_hover: str = "#14B88F"
    accent_pressed: str = "#0C896B"
    danger: str = "#E85D75"
    danger_hover: str = "#F17287"
    danger_pressed: str = "#CE4862"
    warning: str = "#D9A441"
    success: str = "#10A37F"


@dataclass(frozen=True)
class RadiusTokens:
    card: int = 16
    input: int = 12
    button: int = 12
    pill: int = 999


@dataclass(frozen=True)
class SpacingTokens:
    xxs: int = 4
    xs: int = 8
    sm: int = 12
    md: int = 16
    lg: int = 24
    xl: int = 32


COLORS = ColorTokens()
RADII = RadiusTokens()
SPACE = SpacingTokens()

SIDEBAR_WIDTH = 232
