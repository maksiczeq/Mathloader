"""Mathloader — zakładka „Info" (Qt): licencja, autor, podpis."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QPushButton, QScrollArea, QWidget

from config import AppConfig
from version import APP_VERSION
from qtui import anim
from qtui.theme import C, F, I, PAD_LG, PAD_MD, PAD_SM, PAD_XL
from qtui.widgets import ClickableFrame, card, glyph_label, hbox, hline, label, vbox

_LICENSE_PATH = Path(__file__).resolve().parent.parent / "LICENSE"

# Easter egg: 5× klik w numer wersji odblokowuje Opcje Eksperymentalne.
_UNLOCK_CLICKS = 5
# Kolory narzucone przez design — celowo nie idą przez paletę motywu: napis ma
# pozostać tym samym „sekretnym" fioletem niezależnie od ciemnego/jasnego trybu.
_COLOR_PROGRESS = "#4A3868"
_COLOR_DONE = "#694F87"
# Jak długo zostaje zapalona obwódka + napis (po piątym kliku, albo po kliku,
# gdy opcje są już włączone), jeśli użytkownik wcześniej nie zmieni zakładki.
_SUCCESS_MS = 5000
# Musi być identyczny z #VersionClickZone w arkuszu QSS — inaczej animacja
# „skacze" w momencie startu/końca (inny box niż ten, do którego oddaje
# sterowanie). Symetryczny padding = tekst na środku ramki; wyrównanie
# z „Autor:” załatwia `author_row` (patrz jego komentarz).
_ZONE_PADDING = "4px 2px"

_LICENSE_FALLBACK = (
    "MIT License\n\n"
    "Copyright (c) 2026 Maksymilian Borowski\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a "
    "copy of this software and associated documentation files (the "
    '"Software"), to deal in the Software without restriction, including '
    "without limitation the rights to use, copy, modify, merge, publish, "
    "distribute, sublicense, and/or sell copies of the Software, and to permit "
    "persons to whom the Software is furnished to do so, subject to the "
    "following conditions:\n\n"
    "The above copyright notice and this permission notice shall be included "
    "in all copies or substantial portions of the Software.\n\n"
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.'
)


def _license_text() -> str:
    try:
        return _LICENSE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return _LICENSE_FALLBACK


class InfoPage(QWidget):
    """Informacje o programie: licencja MIT + autor + podpis na dole."""

    check_updates_requested = Signal()
    experimental_changed = Signal(bool)

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        self._clicks = 0
        self._border_glowing = False   # czy `border_glow_on` trzyma obwódkę zapaloną
        self._success_timer = QTimer(self)
        self._success_timer.setSingleShot(True)
        self._success_timer.timeout.connect(self._on_success_timeout)
        root = vbox(self, m=PAD_LG, s=PAD_MD)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QFrame()
        holder.setObjectName("Surface")
        L = vbox(holder, m=PAD_XL, s=PAD_MD)

        # ── Nagłówek ──
        head = QWidget(holder)
        hdl = hbox(head, s=PAD_MD)
        hdl.addWidget(glyph_label("APP", obj="AppGlyphXl", parent=head))
        hdl.addWidget(label("Mathloader", "PageTitle"))
        hdl.addStretch(1)
        L.addWidget(head)
        L.addWidget(label("Mathloader — automatyczne pobieranie obrazów lekcji "
                          "matematyki z dynamicznych stron.", "Hint", wrap=True))

        L.addSpacing(PAD_SM)

        # ── Autor ──
        author_row = QWidget(holder)
        al = hbox(author_row, s=PAD_SM)
        # 4px (2px obwódki + 2px paddingu) tyle, ile „Wersja:" niżej traci na
        # wcięcie od własnej (przezroczystej w spoczynku) obwódki — inaczej
        # oba napisy nie zaczynałyby się w tym samym miejscu.
        al.setContentsMargins(4, 0, 0, 0)
        al.addWidget(label("Autor:", "FieldTitle"))
        al.addWidget(label("Maksymilian Borowski", "Accent"))
        al.addStretch(1)
        L.addWidget(author_row)

        ver_row = QWidget(holder)
        vl = hbox(ver_row, s=PAD_SM)

        self.ver_zone = ClickableFrame(ver_row)
        self.ver_zone.setObjectName("VersionClickZone")
        self.ver_zone.setCursor(Qt.CursorShape.PointingHandCursor)
        vzl = hbox(self.ver_zone, s=PAD_SM)
        vzl.addWidget(label("Wersja:", "FieldTitle"))
        vzl.addWidget(label(f"{APP_VERSION}  •  Qt / PySide6", "Hint"))
        self.ver_zone.clicked.connect(self._on_version_click)
        # Bez AlignVCenter hbox rozciągnąłby ramkę do wysokości przycisku
        # „Sprawdź aktualizacje" obok — a tak ramka trzyma się własnej
        # wysokości (tekst + padding) i jest wyśrodkowana w wierszu.
        vl.addWidget(self.ver_zone, 0, Qt.AlignmentFlag.AlignVCenter)
        vl.addStretch(1)

        check = QPushButton(f"{I.REFRESH}   Sprawdź aktualizacje", ver_row)
        check.setObjectName("CardAction")
        check.setMinimumHeight(32)
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.clicked.connect(self.check_updates_requested)
        vl.addWidget(check)
        L.addWidget(ver_row)

        self.unlock_hint = label("", "", wrap=True)
        self.unlock_hint.setTextFormat(Qt.TextFormat.RichText)
        self.unlock_hint.hide()
        L.addWidget(self.unlock_hint)

        L.addSpacing(PAD_SM)
        L.addWidget(hline())
        L.addSpacing(PAD_SM)

        # ── Licencja ──
        L.addWidget(label(f"{I.LICENSE}  Licencja: MIT — otwarte oprogramowanie",
                          "SectionTitle"))
        L.addWidget(label("Możesz swobodnie używać, kopiować, modyfikować i "
                          "rozpowszechniać ten program.", "Hint", wrap=True))

        lic_card = card(holder)
        lcl = vbox(lic_card, m=PAD_LG, s=0)
        lic = label(_license_text(), "License", wrap=True)
        lic.setFont(QFont(F.MONO, F.SIZE_XS))
        lic.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lcl.addWidget(lic)
        L.addWidget(lic_card)

        L.addStretch(1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        # ── Podpis na dole ──
        sign = label("Made with <3 by maksiq", "Signature")
        sign.setTextFormat(Qt.TextFormat.PlainText)
        sign.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont(F.FAMILY, F.SIZE_SM)
        f.setBold(True)
        f.setItalic(True)
        sign.setFont(f)
        root.addWidget(sign)

    # ── easter egg: Opcje Eksperymentalne ──

    def _on_version_click(self) -> None:
        if self._config.experimental_features:
            # Już odblokowane — bez obwódki, tylko przypomnienie, że klik nic
            # więcej nie zrobi.
            self._success_timer.stop()
            self._show_hint(
                f'<span style="color:{_COLOR_PROGRESS}; font-style:italic;'
                f' font-weight:400;">Już włączyłeś Opcje Eksperymentalne</span>')
            self._success_timer.start(_SUCCESS_MS)
            return

        self._clicks += 1

        if self._clicks >= _UNLOCK_CLICKS:
            self._clicks = 0
            self._config.experimental_features = True
            self._config.save()
            self.experimental_changed.emit(True)
            # Ostatni klik: obwódka + tło zapalają się i ZOSTAJĄ zapalone —
            # gasną dopiero po upływie czasu albo przy zmianie zakładki.
            self._border_glowing = True
            anim.border_glow_on(self.ver_zone, C.ACCENT, ms=260, padding=_ZONE_PADDING)
            self._show_hint(
                f'<span style="color:{_COLOR_DONE}; font-weight:700;">'
                f'Włączyłeś Opcje Eksperymentalne!</span>')
            self._success_timer.start(_SUCCESS_MS)
        else:
            # Każdy pozostały klik to tylko krótkie „mignięcie" obwódki.
            anim.border_pulse(self.ver_zone, C.ACCENT, ms=500, padding=_ZONE_PADDING)
            self._success_timer.stop()
            remaining = _UNLOCK_CLICKS - self._clicks
            word = "raz" if remaining == 1 else "razy"
            self._show_hint(
                f'<span style="color:{_COLOR_PROGRESS}; font-weight:400;">'
                f'Kliknij jeszcze {remaining} {word}, by włączyć '
                f'Opcje Eksperymentalne</span>')

    def _show_hint(self, html: str) -> None:
        self.unlock_hint.setText(html)
        self.unlock_hint.show()

    def _hide_hint(self) -> None:
        self.unlock_hint.hide()

    def _on_success_timeout(self) -> None:
        self._hide_hint()
        if self._border_glowing:
            self._border_glowing = False
            anim.border_glow_off(self.ver_zone, C.ACCENT, ms=300, padding=_ZONE_PADDING)

    def hideEvent(self, e) -> None:      # noqa: N802
        super().hideEvent(e)
        # Opuszczenie zakładki kończy bieżącą próbę — licznik, ewentualny
        # napis i zapalona obwódka nie mają po co czekać, skoro nikt już
        # nie patrzy.
        self._success_timer.stop()
        self._clicks = 0
        self._border_glowing = False
        self._hide_hint()
        anim.stop(self.ver_zone, "_border_anim")
        self.ver_zone.setStyleSheet("")
