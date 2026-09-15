"""
Mathloader — motyw wizualny (Qt / PySide6).

Dwie palety (ciemna i jasna), fonty, ikony i generator arkusza QSS.

Kolory czyta się przez `C` — to nie jest klasa ze stałymi, tylko obiekt
przekierowujący każdy odczyt do **aktualnie wybranej** palety. Dzięki temu
`from qtui.theme import C` w pozostałych modułach zostaje bez zmian, a po
`set_theme("light")` te same odwołania (`C.TEXT`) zwracają już jasne wartości.

Uwaga przy dopisywaniu kodu: `C.COŚ` nie nadaje się na **domyślną wartość
argumentu** ani na stałą modułową — zostałoby wyliczone raz, przy imporcie,
i zamrożone na motywie startowym. Kolor pobieraj w środku funkcji.
"""
from __future__ import annotations


class Palette:
    """Zestaw kolorów jednego motywu."""

    def __init__(self, **colors: str):
        self.__dict__.update(colors)


# ── Paleta ciemna (domyślna) ────────────────────────────────────────────────
DARK = Palette(
    BG="#0d1117",
    BG_SURFACE="#161b22",
    BG_CARD="#1c2333",
    BG_CARD_HOVER="#222b3d",
    BG_INPUT="#0d1117",
    BG_HOVER="#1f2937",

    BORDER="#30363d",
    BORDER_FOCUS="#58a6ff",

    PRIMARY="#58a6ff",
    PRIMARY_HOVER="#79b8ff",
    PRIMARY_DARK="#1f6feb",

    ACCENT="#bc8cff",

    SUCCESS="#3fb950",
    SUCCESS_HOVER="#2ea043",
    WARNING="#d29922",
    ERROR="#f85149",
    ERROR_HOVER="#d73a49",

    TEXT="#e6edf3",
    TEXT_SECONDARY="#8b949e",
    TEXT_MUTED="#6e7681",
    TEXT_ON_PRIMARY="#ffffff",
    TEXT_ON_WARNING="#1a1205",

    CHIP_BG="#1f2937",
    CHIP_TEXT="#79b8ff",

    WATERMARK="#1b2231",

    # Konsola i obszar podglądu muszą odcinać się od karty, na której leżą.
    # W ciemnym motywie wystarcza kolor karty, w jasnym potrzebna jest szarość
    # (biel na bieli zlewa się w jedną plamę).
    CONSOLE_BG="#1c2333",
    PREVIEW_BG="#1c2333",

    # stany „wyłączone” i drobiazgi, wcześniej wpisane na sztywno w QSS
    INPUT_DISABLED_BG="#0b0f14",
    DISABLED_BORDER="#262c33",
    PRIMARY_DISABLED_BG="#1b2a44",
    PRIMARY_DISABLED_TEXT="#6b7f9e",
    DANGER_DISABLED_BG="#4a2320",
    DANGER_DISABLED_TEXT="#8d6a67",
    DANGER_SOFT="rgba(248, 81, 73, 0.14)",
    URL_CHIP_HOVER="#ffffff",
    CHIP_EXPIRED="#555a61",
    CHIP_EXPIRED_HOVER="#8a9099",
    SCROLL="#2b3444",
    SCROLL_HOVER="#3a465c",
)

# ── Paleta jasna ────────────────────────────────────────────────────────────
LIGHT = Palette(
    # Hierarchia tła musi zostać zachowana: strona ciemniejsza od panelu,
    # karta odcinająca się od panelu, pole wpisu najjaśniejsze. Same białe
    # karty na białym panelu zlewają się w jedną płaszczyznę.
    BG="#eef1f4",
    BG_SURFACE="#ffffff",
    BG_CARD="#f6f8fa",
    BG_CARD_HOVER="#eef1f4",
    BG_INPUT="#ffffff",
    BG_HOVER="#e7ebef",

    BORDER="#d0d7de",
    BORDER_FOCUS="#0969da",

    PRIMARY="#0969da",
    PRIMARY_HOVER="#218bff",
    PRIMARY_DARK="#0550ae",

    ACCENT="#8250df",

    SUCCESS="#1a7f37",
    SUCCESS_HOVER="#116329",
    WARNING="#d4a72c",
    ERROR="#cf222e",
    ERROR_HOVER="#a40e26",

    TEXT="#1f2328",
    TEXT_SECONDARY="#59636e",
    TEXT_MUTED="#818b98",
    TEXT_ON_PRIMARY="#ffffff",
    TEXT_ON_WARNING="#1a1205",

    CHIP_BG="#ddf4ff",
    CHIP_TEXT="#0969da",

    WATERMARK="#eaeef2",

    CONSOLE_BG="#f2f5f8",
    PREVIEW_BG="#e9edf1",

    INPUT_DISABLED_BG="#f6f8fa",
    DISABLED_BORDER="#d8dee4",
    PRIMARY_DISABLED_BG="#cfe3fb",
    PRIMARY_DISABLED_TEXT="#7d8ea1",
    DANGER_DISABLED_BG="#fbdfe2",
    DANGER_DISABLED_TEXT="#b08d90",
    DANGER_SOFT="rgba(207, 34, 46, 0.10)",
    URL_CHIP_HOVER="#0969da",
    CHIP_EXPIRED="#a0a8b0",
    CHIP_EXPIRED_HOVER="#6e7781",
    SCROLL="#d0d7de",
    SCROLL_HOVER="#afb8c1",
)

PALETTES: dict[str, Palette] = {"dark": DARK, "light": LIGHT}
DEFAULT_THEME = "dark"

_active = DEFAULT_THEME


class _ActiveColors:
    """Proxy: `C.BG` zawsze czyta z palety wybranej przez `set_theme()`."""

    def __getattr__(self, name: str) -> str:
        try:
            return getattr(PALETTES[_active], name)
        except AttributeError as exc:
            raise AttributeError(f"Paleta nie ma koloru {name!r}") from exc


C = _ActiveColors()


def current_theme() -> str:
    return _active


def set_theme(name: str) -> str:
    """Ustawia motyw ('dark'/'light'). Nieznana nazwa → motyw domyślny."""
    global _active
    _active = name if name in PALETTES else DEFAULT_THEME
    return _active


def toggle_theme() -> str:
    """Przełącza na drugi motyw i zwraca jego nazwę."""
    return set_theme("light" if _active == "dark" else "dark")


def is_dark() -> bool:
    return _active == "dark"


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
    SUN        = "☀"
    MOON       = "☾"


I = Icon

# ── Rozmiary / odstępy ──
PAD_XS, PAD_SM, PAD_MD, PAD_LG, PAD_XL, PAD_XXL = 4, 8, 12, 16, 24, 32
RADIUS, RADIUS_SM = 10, 6
CTRL_H = 38


def stylesheet() -> str:
    """Buduje arkusz QSS dla aktualnej palety.

    Wołane przy starcie i po każdym przełączeniu motywu — dlatego jest to
    funkcja, a nie stała modułowa.
    """
    return f"""
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
QLabel#PageTitle  {{ font-size: 20px; font-weight: 800; color: {C.TEXT}; }}
QLabel#WizardTitle {{ font-size: 24px; font-weight: 800; color: {C.TEXT}; }}
QLabel#Accent     {{ font-size: {F.SIZE_SM}px; font-weight: 700; color: {C.PRIMARY}; }}
QLabel#License    {{ color: {C.TEXT_SECONDARY}; background: transparent; }}
QLabel#Signature  {{ color: {C.PRIMARY_DARK}; background: transparent; }}

/* Stany — zamiast wstrzykiwania koloru w kodzie (inaczej nie przełączyłyby
   się razem z motywem). */
QLabel#Ok   {{ font-size: {F.SIZE_XS}px; color: {C.SUCCESS}; }}
QLabel#Warn {{ font-size: {F.SIZE_XS}px; color: {C.WARNING}; }}
QLabel#Err  {{ font-size: {F.SIZE_XS}px; color: {C.ERROR}; }}
QLabel#StatusPct     {{ font-size: {F.SIZE_XS}px; font-weight: 700; color: {C.PRIMARY}; }}
QLabel#StatusPctDone {{ font-size: {F.SIZE_XS}px; font-weight: 700; color: {C.SUCCESS}; }}

/* Historia */
QLabel#LessonNumber {{ font-size: {F.SIZE_MD}px; font-weight: 700; color: {C.PRIMARY}; }}
QLabel#NoTopic      {{ font-size: {F.SIZE_SM}px; font-weight: 700; color: {C.TEXT_MUTED}; }}
QLabel#EmptyState   {{
    font-size: {F.SIZE_XS}px; color: {C.TEXT_MUTED}; padding: {PAD_XXL}px;
}}

QLabel#Watermark  {{
    font-size: {F.SIZE_HUGE}px; font-weight: 800;
    color: {C.WATERMARK}; background: transparent;
}}
QLabel#PreviewArea {{
    background: {C.PREVIEW_BG};
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
QLineEdit:disabled {{ color: {C.TEXT_MUTED}; background: {C.INPUT_DISABLED_BG}; }}
QLineEdit:read-only {{ color: {C.TEXT_SECONDARY}; background: {C.INPUT_DISABLED_BG}; }}
QLineEdit#Mono {{ font-family: "{F.MONO}"; }}
QLineEdit#Small {{ min-height: 30px; }}

QPlainTextEdit#Console {{
    font-family: "{F.MONO}";
    font-size: {F.SIZE_MONO}px;
    background: {C.CONSOLE_BG};
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
QPushButton:disabled {{ color: {C.TEXT_MUTED}; border-color: {C.DISABLED_BORDER}; }}

QPushButton#Primary {{
    background: {C.PRIMARY_DARK};
    border: none; color: {C.TEXT_ON_PRIMARY};
    font-weight: 700; min-height: {CTRL_H}px;
    border-radius: {RADIUS}px; padding: 0 20px;
}}
QPushButton#Primary:hover {{ background: {C.PRIMARY}; }}
QPushButton#Primary:disabled {{
    background: {C.PRIMARY_DISABLED_BG}; color: {C.PRIMARY_DISABLED_TEXT};
}}

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
QPushButton#Danger:hover {{ background: {C.DANGER_SOFT}; }}

QPushButton#DangerSolid {{
    background: {C.ERROR}; border: none; color: #fff; font-weight: 700;
    border-radius: {RADIUS_SM}px; min-height: {CTRL_H}px;
}}
QPushButton#DangerSolid:hover {{ background: {C.ERROR_HOVER}; }}
QPushButton#DangerSolid:disabled {{
    background: {C.DANGER_DISABLED_BG}; color: {C.DANGER_DISABLED_TEXT};
}}

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

/* Przełącznik motywu w nagłówku */
QPushButton#ThemeToggle {{
    background: {C.BG_CARD};
    border: 1px solid {C.BORDER};
    border-radius: 15px;
    min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px;
    padding: 0; font-size: 15px;
    color: {C.TEXT_SECONDARY};
}}
QPushButton#ThemeToggle:hover {{
    background: {C.BG_HOVER}; color: {C.PRIMARY}; border-color: {C.PRIMARY};
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
QPushButton#UrlChip:hover {{
    color: {C.URL_CHIP_HOVER}; border-color: {C.URL_CHIP_HOVER};
}}
QPushButton#UrlChipCopied {{
    background: {C.BG_INPUT}; border: 1px solid {C.SUCCESS};
    color: {C.SUCCESS}; text-align: left; min-height: 30px;
    border-radius: {RADIUS_SM}px; padding: 0 10px;
}}
QPushButton#UrlChipExpired {{
    background: {C.BG_INPUT}; border: none; color: {C.CHIP_EXPIRED};
    text-align: left; min-height: 30px; border-radius: {RADIUS_SM}px; padding: 0 10px;
}}
QPushButton#UrlChipExpired:hover {{ color: {C.CHIP_EXPIRED_HOVER}; }}

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
    background: {C.SCROLL}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {C.SCROLL_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {C.SCROLL}; border-radius: 5px; min-width: 30px; }}

/* ── Dialogi ── */
QDialog {{ background: {C.BG_SURFACE}; }}
QLabel#DialogTitle {{ font-size: {F.SIZE_MD}px; font-weight: 700; }}
QLabel#DialogHint {{ font-size: {F.SIZE_XS}px; color: {C.TEXT_MUTED}; font-style: italic; }}
"""
