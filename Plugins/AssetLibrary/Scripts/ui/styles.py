"""Design tokens and QSS stylesheet matching the HTML mockup (dark mode)."""

# ── Colours ──────────────────────────────────────────────────────────────────
BG_PRIMARY   = "#1e1e1c"
BG_SECONDARY = "#252523"
BG_TERTIARY  = "#2c2c2a"

TEXT_PRIMARY   = "#e8e8e4"
TEXT_SECONDARY = "#a0a09a"
TEXT_TERTIARY  = "#606059"

# Qt rgba() uses 0-255 for alpha
BORDER_LIGHT = "rgba(255,255,255,20)"   # 0.08 opacity
BORDER_MID   = "rgba(255,255,255,36)"   # 0.14 opacity

ACCENT        = "#5ba3e0"
ACCENT_BG     = "#0c2d4a"
ACCENT_BORDER = "#1e5a8a"
ACCENT_TEXT   = "#7bbfee"

GREEN        = "#5DCAA5"
GREEN_BG     = "#042e22"
GREEN_BORDER = "#0F6E56"

GOLD = "#c8a000"

# ── Thumbnail placeholder palettes  [bg, letter_colour] ─────────────────────
THUMB_PALETTES = [
    ("#3d2820", "#e8a090"),
    ("#1a2d3d", "#90b8e0"),
    ("#1e2e20", "#90c8a0"),
    ("#2e2a1a", "#c8b880"),
    ("#281e38", "#a090c8"),
    ("#182828", "#80c0b0"),
    ("#2e1e14", "#c09070"),
    ("#201828", "#9080b0"),
]

# ── Main QSS ─────────────────────────────────────────────────────────────────
def get_stylesheet():
    return f"""
/* Base */
QMainWindow, QDialog {{
    background-color: {BG_PRIMARY};
    color: {TEXT_PRIMARY};
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    font-size: 12px;
}}

QWidget {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_MID};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_MID};
    border-radius: 3px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* Toolbar */
#toolbar {{
    background-color: {BG_SECONDARY};
    border-bottom: 1px solid {BORDER_LIGHT};
}}

/* Search input */
#searchInput {{
    background-color: {BG_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 4px 8px 4px 26px;
    color: {TEXT_PRIMARY};
    font-size: 12px;
}}
#searchInput:focus {{
    border-color: {BORDER_MID};
}}

/* Sort / combo */
QComboBox {{
    background-color: {BG_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 4px 8px;
    color: {TEXT_SECONDARY};
    font-size: 12px;
    min-width: 80px;
}}
QComboBox:hover {{
    border-color: {BORDER_MID};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_TERTIARY};
    width: 0;
    height: 0;
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PRIMARY};
    border: 1px solid {BORDER_MID};
    border-radius: 6px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_BG};
    selection-color: {ACCENT_TEXT};
    padding: 4px;
}}

/* Slider */
QSlider::groove:horizontal {{
    background: {BORDER_LIGHT};
    height: 3px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    border-radius: 5px;
    width: 10px;
    height: 10px;
    margin: -4px 0;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}

/* Generic push buttons */
QPushButton {{
    background-color: transparent;
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 4px 10px;
    color: {TEXT_SECONDARY};
    font-size: 11px;
}}
QPushButton:hover {{
    border-color: {BORDER_MID};
    color: {TEXT_PRIMARY};
    background-color: {BG_PRIMARY};
}}
QPushButton:pressed {{
    background-color: {BG_TERTIARY};
}}

/* Import / publish button */
#importBtn {{
    background-color: {GREEN_BG};
    border: 1px solid {GREEN_BORDER};
    border-radius: 6px;
    padding: 4px 12px;
    color: {GREEN};
    font-size: 11px;
    font-weight: 500;
}}
#importBtn:hover {{
    background-color: #063a2a;
}}

/* Settings (gear) button */
#settingsBtn {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {TEXT_TERTIARY};
    font-size: 14px;
    padding: 0;
}}
#settingsBtn:hover {{
    border-color: {BORDER_LIGHT};
    color: {TEXT_PRIMARY};
}}

/* Filters button active state */
#filtersBtn[active="true"] {{
    background-color: {ACCENT_BG};
    border-color: {ACCENT_BORDER};
    color: {ACCENT_TEXT};
}}

/* Sidebar */
#sidebar {{
    background-color: {BG_SECONDARY};
    border-right: 1px solid {BORDER_LIGHT};
}}

/* Status bar */
#statusBar {{
    background-color: {BG_SECONDARY};
    border-top: 1px solid {BORDER_LIGHT};
}}


/* Dialog fields */
QLineEdit, QTextEdit {{
    background-color: {BG_SECONDARY};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 5px 8px;
    color: {TEXT_PRIMARY};
    font-size: 12px;
}}
QLineEdit:focus, QTextEdit:focus {{
    border-color: {BORDER_MID};
}}

QCheckBox {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {BORDER_LIGHT};
    border-radius: 3px;
    background: {BG_SECONDARY};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* Context menu */
QMenu {{
    background-color: {BG_PRIMARY};
    border: 1px solid {BORDER_MID};
    border-radius: 6px;
    padding: 4px 0;
    color: {TEXT_SECONDARY};
    font-size: 12px;
}}
QMenu::item {{
    padding: 5px 24px 5px 12px;
}}
QMenu::item:selected {{
    background-color: {BG_SECONDARY};
    color: {TEXT_PRIMARY};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER_LIGHT};
    margin: 4px 0;
}}

/* Inspector panel */
#inspectorPanel {{
    background: {BG_SECONDARY};
    border-left: 1px solid {BORDER_LIGHT};
}}

/* Splitter handle */
QSplitter::handle {{
    background: {BORDER_LIGHT};
}}
"""
