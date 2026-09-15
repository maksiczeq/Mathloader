"""Mathloader — zakładka „Info" (Qt): licencja, autor, podpis."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QPushButton, QScrollArea, QWidget

from version import APP_VERSION
from qtui.theme import C, F, I, PAD_LG, PAD_MD, PAD_SM, PAD_XL
from qtui.widgets import card, hbox, hline, label, vbox

_LICENSE_PATH = Path(__file__).resolve().parent.parent / "LICENSE"

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

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        root = vbox(self, m=PAD_LG, s=PAD_MD)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QFrame()
        holder.setObjectName("Surface")
        L = vbox(holder, m=PAD_XL, s=PAD_MD)

        # ── Nagłówek ──
        title = label(f"{I.SPARK}  Mathloader", "AppTitle")
        title.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {C.TEXT};")
        L.addWidget(title)
        L.addWidget(label("Mathloader — automatyczne pobieranie obrazów lekcji "
                          "matematyki z dynamicznych stron.", "Hint", wrap=True))

        L.addSpacing(PAD_SM)

        # ── Autor ──
        author_row = QWidget(holder)
        al = hbox(author_row, s=PAD_SM)
        al.addWidget(label("Autor:", "FieldTitle"))
        who = label("Maksymilian Borowski", "FieldTitle")
        who.setStyleSheet(f"color: {C.PRIMARY};")
        al.addWidget(who)
        al.addStretch(1)
        L.addWidget(author_row)

        ver_row = QWidget(holder)
        vl = hbox(ver_row, s=PAD_SM)
        vl.addWidget(label("Wersja:", "FieldTitle"))
        vl.addWidget(label(f"{APP_VERSION}  •  Qt / PySide6", "Hint"))
        vl.addStretch(1)

        check = QPushButton(f"{I.REFRESH}   Sprawdź aktualizacje", ver_row)
        check.setObjectName("CardAction")
        check.setMinimumHeight(32)
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.clicked.connect(self.check_updates_requested)
        vl.addWidget(check)
        L.addWidget(ver_row)

        L.addSpacing(PAD_SM)
        L.addWidget(hline())
        L.addSpacing(PAD_SM)

        # ── Licencja ──
        L.addWidget(label(f"{I.CHECK}  Licencja: MIT — otwarte oprogramowanie",
                          "SectionTitle"))
        L.addWidget(label("Możesz swobodnie używać, kopiować, modyfikować i "
                          "rozpowszechniać ten program.", "Hint", wrap=True))

        lic_card = card(holder)
        lcl = vbox(lic_card, m=PAD_LG, s=0)
        lic = label(_license_text(), "", wrap=True)
        lic.setFont(QFont(F.MONO, F.SIZE_XS))
        lic.setStyleSheet(f"color: {C.TEXT_SECONDARY}; background: transparent;")
        lic.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lcl.addWidget(lic)
        L.addWidget(lic_card)

        L.addStretch(1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        # ── Podpis na dole ──
        sign = label("Made with <3 by maksiq")
        sign.setTextFormat(Qt.TextFormat.PlainText)
        sign.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont(F.FAMILY, F.SIZE_SM)
        f.setBold(True)
        f.setItalic(True)
        sign.setFont(f)
        sign.setStyleSheet(f"color: {C.PRIMARY_DARK}; background: transparent;")
        root.addWidget(sign)
