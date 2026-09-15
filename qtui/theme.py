"""
Mathloader — motyw wizualny (Qt / PySide6).

Paleta, fonty, ikony i arkusz stylów QSS. Qt renderuje z podwójnym buforowaniem,
więc kolory/rozmiary można animować bez rozdarć — inaczej niż w Tk.
"""
from __future__ import annotations


class C:
    """Paleta kolorów aplikacji (ciemny motyw)."""

    BG              = "#0d1117"
    BG_SURFACE      = "#161b22"
    BG_CARD         = "#1c2333"
    BG_CARD_HOVER   = "#222b3d"
    BG_INPUT        = "#0d1117"
    BG_HOVER        = "#1f2937"

    BORDER          = "#30363d"
    BORDER_FOCUS    = "#58a6ff"

    PRIMARY         = "#58a6ff"
    PRIMARY_HOVER   = "#79b8ff"
    PRIMARY_DARK    = "#1f6feb"

    ACCENT          = "#bc8cff"

    SUCCESS         = "#3fb950"
    SUCCESS_HOVER   = "#2ea043"
    WARNING         = "#d29922"
    ERROR           = "#f85149"
    ERROR_HOVER     = "#d73a49"

    TEXT            = "#e6edf3"
    TEXT_SECONDARY  = "#8b949e"
    TEXT_MUTED      = "#6e7681"
    TEXT_ON_PRIMARY = "#ffffff"
    TEXT_ON_WARNING = "#1a1205"

    CHIP_BG         = "#1f2937"
    CHIP_TEXT       = "#79b8ff"

    WATERMARK       = "#1b2231"


class F:
    """Rodziny i rozmiary fontów."""

    FAMILY = "Segoe UI"
    MONO   = "Consolas"

    SIZE_XL     = 22
    SIZE_LG     = 17
    SIZE_MD     = 14
    SIZE_SM     = 12
    SIZE_XS     = 11
    SIZE_MONO   = 11
    SIZE_HUGE   = 76   # znak wodny


class Icon:
    """Piktogramy Unicode — renderują się w kolorze tekstu."""

    DOWNLOAD   = "⬇"
    REFRESH    = "↻"
    SCAN       = "◌"
    CHECK      = "✓"
    CROSS      = "✕"
    GEAR       = "⚙"
    WARN       = "⚠"
    STOP       = "⛔"
    LIST       = "☰"
    CHEVRON_D  = "⌄"
    CHEVRON_U  = "⌃"
    TRI_RIGHT  = "▸"
    TRI_DOWN   = "▾"
    ARROW_R    = "→"
    ARROW_L    = "←"
    OPEN       = "↗"
    ERASE      = "⌫"
    FOLDER     = "▰"
    NAME_TAG   = "▤"
    SLIDERS    = "≡"
    SPARK      = "✦"
    DOT        = "●"
    PLUS       = "＋"
    INFO       = "ℹ"
    HEART      = "♥"


I = Icon

# ── Rozmiary / odstępy ──
PAD_XS, PAD_SM, PAD_MD, PAD_LG, PAD_XL, PAD_XXL = 4, 8, 12, 16, 24, 32
RADIUS, RADIUS_SM = 10, 6
CTRL_H = 38


STYLESHEET = f"""
* {{
    font-family: "{F.FAMILY}";
    font-size: {F.SIZE_SM}px;
    color: {C.TEXT};
    outline: none;
}}

QWidget#Root, QMainWindow {{ background: {C.BG}; }}

QToolTip {{
    background: {C.BG_CARD};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 4px 8px;
}}

/* ── Karty / powierzchnie ── */
QFrame#Card {{
    background: {C.BG_CARD};
    border-radius: {RADIUS}px;
}}
QFrame#Surface {{
    background: {C.BG_SURFACE};
    border-radius: {RADIUS}px;
}}
QFrame#Separator {{ background: {C.BORDER}; border: none; }}

/* ── Nagłówki i teksty ── */
QLabel#AppTitle   {{ font-size: {F.SIZE_LG}px; font-weight: 700; color: {C.TEXT}; }}
QLabel#AppVersion {{ font-size: {F.SIZE_XS}px; color: {C.TEXT_MUTED}; }}
QLabel#SectionTitle {{ font-size: {F.SIZE_MD}px; font-weight: 700; color: {C.TEXT}; }}
QLabel#FieldTitle {{ font-size: {F.SIZE_SM}px; font-weight: 700; color: {C.TEXT}; }}
QLabel#Hint       {{ font-size: {F.SIZE_XS}px; color: {C.TEXT_SECONDARY}; }}
QLabel#Muted      {{ font-size: {F.SIZE_XS}px; color: {C.TEXT_MUTED}; }}
QLabel#Watermark  {{
    font-size: {F.SIZE_HUGE}px; font-weight: 800;
    color: {C.WATERMARK}; background: transparent;
}}
QLabel#PreviewArea {{
    background: {C.BG_CARD};
    border-radius: {RADIUS_SM}px;
    color: {C.TEXT_SECONDARY};
}}

/* ── Pola tekstowe ── */
QLineEdit {{
    background: {C.BG_INPUT};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 0 10px;
    min-height: {CTRL_H}px;
    selection-background-color: {C.PRIMARY_DARK};
}}
QLineEdit:focus {{ border-color: {C.BORDER_FOCUS}; }}
QLineEdit:disabled {{ color: {C.TEXT_MUTED}; background: #0b0f14; }}
QLineEdit#Mono {{ font-family: "{F.MONO}"; }}
QLineEdit#Small {{ min-height: 30px; }}

QPlainTextEdit#Console {{
    font-family: "{F.MONO}";
    font-size: {F.SIZE_MONO}px;
    background: {C.BG_CARD};
    color: {C.TEXT_SECONDARY};
    border: none;
    border-radius: {RADIUS}px;
    padding: 8px 10px;
}}

/* ── Przyciski ── */
QPushButton {{
    background: {C.BG_CARD};
    border: 1px solid {C.BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 0 14px;
    min-height: 30px;
    color: {C.TEXT};
}}
QPushButton:hover {{ background: {C.BG_HOVER}; }}
QPushButton:pressed {{ background: {C.BG_INPUT}; }}
QPushButton:disabled {{ color: {C.TEXT_MUTED}; border-color: #262c33; }}

QPushButton#Primary {{
    background: {C.PRIMARY_DARK};
    border: none; color: {C.TEXT_ON_PRIMARY};
    font-weight: 700; min-height: {CTRL_H}px;
    border-radius: {RADIUS}px; padding: 0 20px;
}}
QPushButton#Primary:hover {{ background: {C.PRIMARY}; }}
QPushButton#Primary:disabled {{ background: #1b2a44; color: #6b7f9e; }}

QPushButton#Success {{
    background: {C.SUCCESS};
    border: none; color: {C.TEXT_ON_PRIMARY};
    font-weight: 700; min-height: {CTRL_H}px;
    border-radius: {RADIUS}px;
}}
QPushButton#Success:hover {{ background: {C.SUCCESS_HOVER}; }}

QPushButton#Danger {{
    background: transparent;
    border: 1px solid {C.ERROR}; color: {C.ERROR};
    font-weight: 700; border-radius: {RADIUS}px; min-height: 34px;
}}
QPushButton#Danger:hover {{ background: rgba(248, 81, 73, 0.14); }}

QPushButton#DangerSolid {{
    background: {C.ERROR}; border: none; color: #fff; font-weight: 700;
    border-radius: {RADIUS_SM}px; min-height: {CTRL_H}px;
}}
QPushButton#DangerSolid:hover {{ background: {C.ERROR_HOVER}; }}
QPushButton#DangerSolid:disabled {{ background: #4a2320; color: #8d6a67; }}

QPushButton#Ghost {{
    background: transparent; border: none; color: {C.TEXT_SECONDARY};
    padding: 0 8px; min-height: 24px;
}}
QPushButton#Ghost:hover {{ color: {C.TEXT}; }}

QPushButton#Link {{
    background: transparent; border: none;
    color: {C.TEXT_ON_WARNING}; text-decoration: underline;
    padding: 0; min-height: 20px; text-align: left;
}}

QPushButton#IconDanger {{
    background: {C.BG}; border: 1px solid {C.BORDER}; color: {C.ERROR};
    border-radius: {RADIUS_SM}px; min-height: 30px; max-width: 36px; padding: 0;
    font-weight: 700;
}}
QPushButton#IconDanger:hover {{ background: {C.ERROR}; color: #fff; border-color: {C.ERROR}; }}

QPushButton#CardAction {{
    background: {C.BG}; border: 1px solid {C.BORDER}; color: {C.TEXT};
    min-height: 30px; border-radius: {RADIUS_SM}px;
}}
QPushButton#CardAction:hover {{ background: {C.BG_HOVER}; }}

QPushButton#UrlChip {{
    background: {C.BG_INPUT}; border: 1px solid {C.BORDER};
    color: {C.TEXT_MUTED}; text-align: left; min-height: 30px;
    border-radius: {RADIUS_SM}px; padding: 0 10px;
}}
QPushButton#UrlChip:hover {{ color: #ffffff; border-color: #ffffff; }}
QPushButton#UrlChipExpired {{
    background: {C.BG_INPUT}; border: none; color: #555a61;
    text-align: left; min-height: 30px; border-radius: {RADIUS_SM}px; padding: 0 10px;
}}
QPushButton#UrlChipExpired:hover {{ color: #8a9099; }}

QPushButton#Chip {{
    background: {C.CHIP_BG}; border: none; color: {C.CHIP_TEXT};
    font-weight: 700; font-size: {F.SIZE_XS}px;
    border-radius: {RADIUS_SM}px; padding: 0 10px; min-height: 26px;
}}
QPushButton#Chip:hover {{ background: {C.BG_HOVER}; }}

QPushButton#Collapse {{
    background: transparent; border: none; text-align: left;
    font-size: {F.SIZE_MD}px; font-weight: 700; color: {C.TEXT};
    padding: 6px 4px; min-height: 32px;
}}
QPushButton#Collapse:hover {{ color: {C.PRIMARY}; }}

QPushButton#AddPath {{
    background: {C.BG_CARD}; border: 1px dashed {C.BORDER};
    color: {C.PRIMARY}; font-weight: 700; min-height: {CTRL_H}px;
    border-radius: {RADIUS_SM}px;
}}
QPushButton#AddPath:hover {{ background: {C.BG_HOVER}; border-color: {C.PRIMARY}; }}

/* ── Zakładki (własny pasek na QPushButton) ── */
QPushButton#Tab {{
    background: transparent; border: none; color: {C.TEXT_SECONDARY};
    font-weight: 700; padding: 0 18px; min-height: 32px;
    border-radius: {RADIUS_SM}px;
}}
QPushButton#Tab:hover {{ color: {C.TEXT}; background: {C.BG_HOVER}; }}
QPushButton#Tab:checked {{ background: {C.PRIMARY_DARK}; color: {C.TEXT_ON_PRIMARY}; }}
QFrame#TabBar {{ background: {C.BG_CARD}; border-radius: {RADIUS}px; }}

/* ── Pasek postępu ── */
QProgressBar {{
    background: {C.BG};
    border: none; border-radius: 4px;
    max-height: 8px; min-height: 8px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {C.PRIMARY}; border-radius: 4px; }}
QProgressBar#Done::chunk {{ background: {C.SUCCESS}; }}

/* ── Combo ── */
QComboBox {{
    background: {C.BG_INPUT}; border: 1px solid {C.BORDER};
    border-radius: {RADIUS_SM}px; padding: 0 10px; min-height: 30px;
    font-weight: 700; font-size: {F.SIZE_XS}px;
}}
QComboBox:hover {{ border-color: {C.PRIMARY_DARK}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background: {C.BG_CARD}; border: 1px solid {C.BORDER};
    selection-background-color: {C.PRIMARY_DARK};
    outline: none; padding: 4px;
}}

/* ── Scroll ── */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #2b3444; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3a465c; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2b3444; border-radius: 5px; min-width: 30px; }}

/* ── Dialogi ── */
QDialog {{ background: {C.BG_SURFACE}; }}
QLabel#DialogTitle {{ font-size: {F.SIZE_MD}px; font-weight: 700; }}
QLabel#DialogHint {{ font-size: {F.SIZE_XS}px; color: {C.TEXT_MUTED}; font-style: italic; }}
"""
