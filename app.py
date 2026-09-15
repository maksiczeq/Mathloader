#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mathloader — punkt wejścia GUI (PySide6 / Qt 6).

  1. Wskazuje Playwright na dołączoną przeglądarkę (tylko w wersji zbudowanej)
  2. Wczytuje konfigurację (settings.json)
  3. Przy pierwszym uruchomieniu pokazuje kreator konfiguracji
  4. Następnie otwiera główne okno z zakładkami

Uruchom: python app.py
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

# Upewnij się, że katalog projektu jest w sys.path
_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import paths

# MUSI być przed pierwszym uruchomieniem Playwright.
paths.setup_playwright_env()

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from config import AppConfig
from qtui.theme import F, set_theme, stylesheet

ICON_PATH = paths.bundle_dir() / "assets" / "mathloader.ico"


def _log_crash(exc_type, exc_value, exc_tb) -> str:
    """Dopisuje wyjątek do logu i zwraca sformatowany ślad stosu."""
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(paths.log_file(), "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}")
    except OSError:
        pass
    return text


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    """W wersji okienkowej nie ma konsoli — pokaż błąd zamiast cicho zniknąć."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    text = _log_crash(exc_type, exc_value, exc_tb)
    if QApplication.instance() is not None:
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Mathloader — błąd")
        box.setText("Wystąpił nieoczekiwany błąd.")
        box.setInformativeText(f"Szczegóły zapisano w:\n{paths.log_file()}")
        box.setDetailedText(text)
        box.exec()


def main() -> int:
    sys.excepthook = _excepthook

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Mathloader")
    app.setStyle("Fusion")
    app.setFont(QFont(F.FAMILY, F.SIZE_SM))
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    config = AppConfig().load()
    # Motyw musi być wybrany PRZED zbudowaniem arkusza — przy pierwszym
    # uruchomieniu (brak settings.json) `config.theme` zwraca „dark”.
    set_theme(config.theme)
    app.setStyleSheet(stylesheet())

    if config.is_first_run():
        from qtui.setup_wizard import SetupWizard
        wizard = SetupWizard(config)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return 0                      # użytkownik zamknął kreator
        config.load()                     # odśwież po zapisie

    from qtui.main_window import MainWindow
    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
