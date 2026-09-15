"""Mathloader — kreator pierwszego uruchomienia (Qt)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QPushButton, QWidget

from config import AppConfig
from qtui import anim
from qtui.theme import C, I, PAD_LG, PAD_MD, PAD_XL, STYLESHEET
from qtui.settings_page import SettingsForm
from qtui.widgets import label, vbox


class SetupWizard(QDialog):
    """Okno konfiguracji przy pierwszym starcie (bez maksymalizacji)."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config

        self.setWindowTitle("Mathloader — Konfiguracja")
        self.setStyleSheet(STYLESHEET)
        self.setModal(True)
        self.setFixedSize(760, 720)
        # Jak w oknie głównym: bez MSWindowsFixedSizeDialogHint ramka dalej
        # łapie kursor rozciągania, choć rozmiar i tak się nie zmienia.
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )

        lay = vbox(self, m=PAD_XL, s=PAD_MD)

        title = label(f"{I.SPARK}  Witaj w Mathloader!", "AppTitle")
        title.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {C.TEXT};")
        lay.addWidget(title)
        lay.addWidget(label("Skonfiguruj aplikację przed pierwszym użyciem.",
                            "Hint"))
        lay.addSpacing(PAD_MD)

        self.form = SettingsForm(config, offer_factory_reset=False)
        lay.addWidget(self.form, 1)

        self.error = label("", "Hint", wrap=True)
        self.error.setStyleSheet(f"color: {C.ERROR};")
        lay.addWidget(self.error)

        start = QPushButton(f"Zapisz i rozpocznij   {I.ARROW_R}", self)
        start.setObjectName("Primary")
        start.setMinimumHeight(46)
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        start.clicked.connect(self._save)
        lay.addWidget(start)

    def showEvent(self, e) -> None:       # noqa: N802
        super().showEvent(e)
        anim.fade_in_window(self, ms=280)

    def _save(self) -> None:
        errors = self.form.validate()
        if errors:
            self.error.setText(f"{I.WARN}  " + " • ".join(errors))
            anim.fade_in(self.error, ms=anim.FAST)
            return
        self.form.apply_to_config(self._config)
        # mark_setup_complete() zapisuje flagę w _data ORAZ na dysk —
        # samo `self._config.setup_completed = True` tworzyłoby martwy atrybut
        # (brak settera), przez co kreator wracał przy każdym starcie.
        self._config.mark_setup_complete()
        self.accept()
