"""四种界面风格。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    id: str
    bg: str
    text: str
    muted: str
    accent: str
    accent_text: str
    input: str
    line: str
    chip: str
    card: str
    card_due: str
    danger: str
    bar: str
    border: str


THEMES: dict[str, Theme] = {
    "ink": Theme(
        id="ink",
        bg="#17191f",
        text="#f4f1ea",
        muted="#8b919c",
        accent="#e2a33a",
        accent_text="#1a1408",
        input="#2a2f3a",
        line="#3a4050",
        chip="#262b36",
        card="#222733",
        card_due="#3a3122",
        danger="#e36b6b",
        bar="#e2a33a",
        border="#ffffff22",
    ),
    "paper": Theme(
        id="paper",
        bg="#f6f1e7",
        text="#2c261c",
        muted="#7a7166",
        accent="#9a6232",
        accent_text="#fffaf3",
        input="#fffaf3",
        line="#e0d5c4",
        chip="#efe6d6",
        card="#fffaf3",
        card_due="#f3e2c4",
        danger="#b94a48",
        bar="#c47b2d",
        border="#00000018",
    ),
    "forest": Theme(
        id="forest",
        bg="#14211c",
        text="#e7f2ea",
        muted="#8aa394",
        accent="#b6d96a",
        accent_text="#14210f",
        input="#1d2e27",
        line="#2d463a",
        chip="#24382f",
        card="#1c2c25",
        card_due="#314328",
        danger="#e07a7a",
        bar="#b6d96a",
        border="#ffffff18",
    ),
    "dusk": Theme(
        id="dusk",
        bg="#1b1730",
        text="#f3eefe",
        muted="#a399b8",
        accent="#d7b4ff",
        accent_text="#241433",
        input="#272042",
        line="#3d345c",
        chip="#2a2348",
        card="#241d3d",
        card_due="#3a2d52",
        danger="#ff8f9a",
        bar="#d7b4ff",
        border="#ffffff18",
    ),
}


def theme_by_id(theme_id: str) -> Theme:
    return THEMES.get(theme_id) or THEMES["ink"]


def stylesheet(theme: Theme) -> str:
    return f"""
    QLabel#appName {{ color: {theme.text}; font-size: 20px; font-weight: 800; background: transparent; }}
    QLabel#appSub, QLabel#hint, QLabel#footer, QLabel#section {{
        color: {theme.muted}; font-size: 12px; background: transparent;
    }}
    QLabel#dayCaption {{ color: {theme.text}; font-size: 13px; font-weight: 650; background: transparent; }}
    QLineEdit {{
        background: {theme.input};
        border: 1px solid {theme.line};
        border-radius: 10px;
        padding: 8px 10px;
        color: {theme.text};
        font-size: 14px;
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QLineEdit:focus {{ border-color: {theme.accent}; }}
    QPushButton#ghost, QPushButton#pin, QPushButton#tiny {{
        background: transparent;
        color: {theme.text};
        border: 1px solid {theme.line};
        border-radius: 8px;
        padding: 5px 8px;
    }}
    QPushButton#ghost:hover, QPushButton#pin:hover, QPushButton#tiny:hover {{ background: {theme.chip}; }}
    QPushButton#pin:checked {{
        background: {theme.card_due};
        color: {theme.accent};
        border-color: {theme.accent};
    }}
    QPushButton#primary {{
        background: {theme.accent};
        color: {theme.accent_text};
        border: none;
        border-radius: 8px;
        padding: 6px 14px;
        font-weight: 700;
    }}
    QPushButton#chip {{
        background: {theme.chip};
        color: {theme.text};
        border: none;
        border-radius: 9px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    QPushButton#chip:hover {{ border: 1px solid {theme.accent}; }}
    QPushButton#timeLink, QPushButton#timeDue {{
        background: transparent;
        border: none;
        padding: 0;
        font-size: 12px;
        font-weight: 700;
    }}
    QPushButton#timeLink {{ color: {theme.accent}; }}
    QPushButton#timeDue {{ color: {theme.accent}; }}
    QPushButton#dangerIcon {{
        background: transparent;
        color: {theme.muted};
        border: none;
        font-size: 16px;
    }}
    QPushButton#dangerIcon:hover {{ color: {theme.danger}; }}
    QFrame#rule {{ color: {theme.line}; max-height: 1px; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QWidget#settings {{ background: {theme.card}; border-radius: 12px; }}
    QLabel#setLabel {{ color: {theme.muted}; font-size: 12px; background: transparent; }}
    QSlider::groove:horizontal {{ height: 4px; background: {theme.line}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 14px; margin: -6px 0; background: {theme.accent}; border-radius: 7px;
    }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 0; }}
    QScrollBar::handle:vertical {{ background: {theme.line}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """
