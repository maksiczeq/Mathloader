"""Mathloader — wspólne komponenty UI (Qt)."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from qtui import anim
from qtui.theme import C, G, I, PAD_MD, PAD_SM, PAD_XL, RADIUS, icon_font


def card(parent: Optional[QWidget] = None, *, surface: bool = False) -> QFrame:
    f = QFrame(parent)
    f.setObjectName("Surface" if surface else "Card")
    return f


def hline(parent: Optional[QWidget] = None) -> QFrame:
    f = QFrame(parent)
    f.setObjectName("Separator")
    f.setFixedHeight(1)
    return f


def label(text: str, obj: str = "", *, wrap: bool = False,
          parent: Optional[QWidget] = None) -> QLabel:
    lb = QLabel(text, parent)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def vbox(w: QWidget, m: int = 0, s: int = 0) -> QVBoxLayout:
    lay = QVBoxLayout(w)
    lay.setContentsMargins(m, m, m, m)
    lay.setSpacing(s)
    return lay


def hbox(w: QWidget, m: int = 0, s: int = 0) -> QHBoxLayout:
    lay = QHBoxLayout(w)
    lay.setContentsMargins(m, m, m, m)
    lay.setSpacing(s)
    return lay


# ── Ikony z fontu systemowego ───────────────────────────────────────────────

def glyph_label(name: str, *, obj: str = "Glyph",
                parent: Optional[QWidget] = None) -> QLabel:
    """Etykieta z jedną ikoną z fontu systemowego.

    Rodzinę (i rozmiar) nadaje QSS po `objectName` — `setFont()` przegrałoby tu
    z regułą `*` z początku arkusza i zamiast ikony wyszedłby pusty prostokąt.
    Stąd `obj`: „Glyph", „GlyphLg", „GlyphXl", „AppGlyph", „AppGlyphXl".
    """
    lb = QLabel(getattr(G, name), parent)
    lb.setObjectName(obj)
    return lb


def glyph_icon(name: str, color: str, size: int = 16) -> QIcon:
    """Ikona z fontu systemowego wypalona w pixmapę o zadanym kolorze.

    Tylko dla kolorów NIEZALEŻNYCH od motywu (biel na niebieskim/zielonym/
    czerwonym przycisku). Kolor zależny od palety zostałby w pixmapie z
    poprzedniego motywu — QSS takiej ikony nie przemaluje.

    Rysujemy w podwójnej skali i oznaczamy pixmapę jako 2×, żeby na ekranie
    z DPI 150–200% ikona nie wyszła rozmyta.
    """
    family = icon_font()
    if not family:
        return QIcon()

    def _draw(pen: QColor) -> QPixmap:
        pm = QPixmap(size * 2, size * 2)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(family)
        font.setPixelSize(size * 2)
        painter.setFont(font)
        painter.setPen(pen)
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, getattr(G, name))
        painter.end()
        pm.setDevicePixelRatio(2.0)
        return pm

    normal = QColor(color)
    faded = QColor(color)
    faded.setAlpha(100)
    icon = QIcon(_draw(normal))
    # Wariant dla przycisku wyłączonego rysujemy sami: styl przygasza napis,
    # ale gotową pixmapę zostawiłby w pełnej jasności i ikona odstawałaby.
    icon.addPixmap(_draw(faded), QIcon.Mode.Disabled)
    return icon


def set_glyph(button: QPushButton, name: str, *, color: str = "#ffffff",
              size: int = 16) -> None:
    """Wstawia ikonę w przycisk z tekstem (bez fontu ikon nie robi nic)."""
    icon = glyph_icon(name, color, size)
    if not icon.isNull():
        button.setIcon(icon)
        button.setIconSize(QSize(size, size))


def restyle(w: QWidget) -> None:
    """Wymusza ponowne dopasowanie QSS po zmianie objectName widgetu."""
    w.style().unpolish(w)
    w.style().polish(w)


class TabBar(QWidget):
    """Segmentowany pasek zakładek (własny — spójny z motywem)."""

    def __init__(self, titles: list[str], on_change: Callable[[int], None],
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._on_change = on_change
        outer = hbox(self)
        outer.addStretch(1)

        box = QFrame(self)
        box.setObjectName("TabBar")
        lay = hbox(box, m=4, s=4)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, t in enumerate(titles):
            b = QPushButton(t, box)
            b.setObjectName("Tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if i == 0:
                b.setChecked(True)
            self._group.addButton(b, i)
            lay.addWidget(b)

        self._group.idClicked.connect(self._on_change)
        outer.addWidget(box)
        outer.addStretch(1)

    def set_index(self, idx: int) -> None:
        btn = self._group.button(idx)
        if btn:
            btn.setChecked(True)
            self._on_change(idx)


class CollapsibleSection(QWidget):
    """Sekcja zwijana z animacją wysokości (płynna dzięki Qt)."""

    def __init__(self, title: str, *, expanded: bool = False,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._title = title
        self._expanded = expanded

        lay = vbox(self, s=PAD_SM)

        self.header = QPushButton(self._header_text(), self)
        self.header.setObjectName("Collapse")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.clicked.connect(self.toggle)
        lay.addWidget(self.header)

        self.body = QWidget(self)
        self.body_layout = vbox(self.body, s=PAD_MD)
        lay.addWidget(self.body)
        self.body.setVisible(expanded)

    def _header_text(self) -> str:
        arrow = I.TRI_DOWN if self._expanded else I.TRI_RIGHT
        return f"{arrow}   {self._title}"

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self.header.setText(self._header_text())
        if self._expanded:
            anim.slide_down(self.body, ms=anim.BASE)
            anim.fade_in(self.body, ms=anim.BASE)
        else:
            anim.slide_up(self.body, ms=anim.FAST)

    def is_expanded(self) -> bool:
        return self._expanded


class BaseDialog(QDialog):
    """Modal z płynnym pojawieniem się."""

    def __init__(self, parent: Optional[QWidget], title: str, width: int = 430):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

    def showEvent(self, e) -> None:      # noqa: N802
        super().showEvent(e)
        anim.fade_in_window(self, ms=anim.FAST + 40)


class ConfirmDialog(BaseDialog):
    """Potwierdzenie akcji: tytuł, treść, opcjonalna kursywna podpowiedź."""

    def __init__(self, parent: Optional[QWidget], *, title: str, message: str,
                 hint: str = "", confirm_text: str = "Usuń",
                 danger: bool = True):
        super().__init__(parent, title)
        lay = vbox(self, m=PAD_XL, s=PAD_MD)

        msg = label(message, "DialogTitle", wrap=True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(msg)

        if hint:
            h = label(hint, "DialogHint", wrap=True)
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(h)

        lay.addSpacing(PAD_SM)

        row = QWidget(self)
        rl = hbox(row, s=PAD_MD)
        ok = QPushButton(f"  {confirm_text}", row)
        ok.setObjectName("DangerSolid" if danger else "Primary")
        set_glyph(ok, "CHECK")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.accept)

        no = QPushButton("Nie", row)
        no.setObjectName("CardAction")
        no.setMinimumHeight(38)
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.clicked.connect(self.reject)

        rl.addWidget(ok, 1)
        rl.addWidget(no, 1)
        lay.addWidget(row)


class TypeToConfirmDialog(BaseDialog):
    """Destrukcyjna akcja — wymaga przepisania słowa kluczowego."""

    def __init__(self, parent: Optional[QWidget], *, title: str, heading: str,
                 message: str, keyword: str, confirm_text: str):
        super().__init__(parent, title, width=480)
        self._keyword = keyword
        lay = vbox(self, m=PAD_XL, s=PAD_MD)

        head = label(f"{I.WARN}  {heading}", "DialogTitle", wrap=True)
        head.setStyleSheet(f"color: {C.ERROR};")
        lay.addWidget(head)

        lay.addWidget(label(message, "Hint", wrap=True))
        lay.addSpacing(PAD_SM)
        lay.addWidget(label(f'Wpisz „{keyword}", aby potwierdzić:', "FieldTitle"))

        self.entry = QLineEdit(self)
        self.entry.textChanged.connect(self._on_type)
        lay.addWidget(self.entry)
        lay.addSpacing(PAD_SM)

        row = QWidget(self)
        rl = hbox(row, s=PAD_MD)
        self.ok = QPushButton(confirm_text, row)
        self.ok.setObjectName("DangerSolid")
        self.ok.setEnabled(False)
        self.ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok.clicked.connect(self.accept)

        no = QPushButton("Anuluj", row)
        no.setObjectName("CardAction")
        no.setMinimumHeight(38)
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.clicked.connect(self.reject)

        rl.addWidget(self.ok, 1)
        rl.addWidget(no, 1)
        lay.addWidget(row)

    def _on_type(self, text: str) -> None:
        self.ok.setEnabled(text.strip() == self._keyword)


class Toast(QFrame):
    """Krótki komunikat w rogu (np. „Skopiowano")."""

    # Kolor domyślny rozwiązujemy w środku: `C.SUCCESS` w sygnaturze zostałby
    # wyliczony raz, przy imporcie, i nie nadążałby za zmianą motywu.
    def __init__(self, parent: QWidget, text: str, color: str = ""):
        super().__init__(parent)
        color = color or C.SUCCESS
        self.setObjectName("ToastBox")
        self.setStyleSheet(
            f"#ToastBox {{ background: {C.BG_CARD}; border: 1px solid {color};"
            f" border-radius: {RADIUS}px; }}"
        )
        lay = hbox(self, m=PAD_MD, s=PAD_SM)
        lb = QLabel(text, self)
        lb.setStyleSheet(f"color: {color}; font-weight: 700;")
        lay.addWidget(lb)
        self.adjustSize()

    @staticmethod
    def show_at(parent: QWidget, text: str, color: str = "",
                ms: int = 1400) -> None:
        t = Toast(parent, text, color)
        t.move(parent.width() - t.width() - PAD_XL,
               parent.height() - t.height() - PAD_XL)
        anim.fade_in(t, ms=anim.FAST)
        QTimer.singleShot(ms, lambda: anim.fade_out(t, ms=anim.FAST,
                                                    on_done=t.deleteLater))
