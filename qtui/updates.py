"""
Mathloader — warstwa okienkowa sprawdzania aktualizacji.

Sama logika siedzi w `updater.py`; tutaj jest tylko: zadanie w tle + pokazanie
komunikatu. Komunikat celowo jest oknem SYSTEMOWYM (Win32 TaskDialog), a nie
dialogiem w motywie aplikacji — informacja o nowej wersji ma wyglądać jak
komunikat Windows, żeby użytkownik traktował ją poważnie.

Tryby:
  • automatyczny (start aplikacji) — cisza, gdy brak nowej wersji albo brak sieci
  • ręczny („Sprawdź aktualizacje” w zakładce Info) — zawsze pokazuje wynik
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from config import AppConfig
from updater import UpdateInfo
from version import APP_VERSION, GITHUB_OWNER, GITHUB_REPO, is_repo_configured
from qtui import native_dialogs as nd
from qtui.workers import UpdateJob

DIALOG_TITLE = "Mathloader — aktualizacja"

BTN_DOWNLOAD = 101
BTN_LATER = 102
BTN_SKIP = 103

START_DELAY_MS = 1800          # daj oknu wstać, zanim wyskoczy komunikat


class UpdateChecker(QObject):
    """Sprawdza wydania na GitHubie i pokazuje systemowy komunikat."""

    def __init__(self, window: QWidget, config: AppConfig):
        super().__init__(window)
        self._window = window
        self._config = config
        # Referencji na zadanie NIE zwalniamy w slocie `done` — wątek roboczy
        # wysyła jeszcze `finished`, a sprzątnięty obiekt nie miałby dokąd.
        # Zwalnia ją dopiero kolejne sprawdzenie, podmieniając obiekt.
        self._job: Optional[UpdateJob] = None
        self._busy = False
        self._manual = False

    # ────────────────────────────── uruchomienie

    def check_on_start(self) -> None:
        """Cichy test przy starcie — z opóźnieniem, żeby nie zasłonić okna."""
        if not self._config.check_updates or not is_repo_configured():
            return
        QTimer.singleShot(START_DELAY_MS, lambda: self.check(manual=False))

    def check(self, *, manual: bool = False) -> None:
        if self._busy:                            # jedno sprawdzanie naraz
            return
        if not is_repo_configured():
            if manual:
                self._info(
                    "Sprawdzanie aktualizacji nie jest skonfigurowane",
                    "W pliku version.py trzeba wpisać login GitHub w polu "
                    "GITHUB_OWNER — dopiero wtedy aplikacja wie, gdzie szukać "
                    "nowych wersji.",
                    icon=nd.ICON_WARNING)
            return

        self._manual = manual
        self._busy = True
        self._job = UpdateJob(APP_VERSION)
        self._job.done.connect(self._on_done)
        self._job.failed.connect(self._on_failed)
        self._job.start()

    # ────────────────────────────── wyniki

    def _on_done(self, info: Optional[UpdateInfo]) -> None:
        manual, self._manual = self._manual, False
        self._busy = False

        if info is None:
            if manual:
                self._info(
                    "Masz najnowszą wersję",
                    f"Mathloader {APP_VERSION} jest aktualny — nic do pobrania.")
            return

        if not manual and info.version == self._config.skip_version:
            return                                 # użytkownik pominął tę wersję

        self._show_update(info)

    def _on_failed(self, message: str) -> None:
        manual, self._manual = self._manual, False
        self._busy = False
        if manual:
            self._info("Nie udało się sprawdzić aktualizacji", message,
                       icon=nd.ICON_WARNING)

    # ────────────────────────────── komunikaty

    def _hwnd(self) -> int:
        try:
            return int(self._window.winId())
        except (RuntimeError, TypeError):
            return 0

    def _show_update(self, info: UpdateInfo) -> None:
        when = f" (wydana {info.published})" if info.published else ""
        content = (
            f"Używasz wersji {APP_VERSION}, a dostępna jest wersja "
            f"{info.version}{when}.\n\n"
            "Pobranie otworzy stronę GitHuba w przeglądarce. Instalator "
            "nadpisze obecną wersję — ustawienia i historia lekcji zostaną "
            "zachowane."
        )
        pressed = nd.task_dialog(
            title=DIALOG_TITLE,
            heading="Dostępna nowa wersja aplikacji",
            content=content,
            buttons=[
                nd.Button(BTN_DOWNLOAD,
                          f"Pobierz wersję {info.version}\n"
                          "Otwiera stronę pobierania w przeglądarce."),
                nd.Button(BTN_LATER,
                          "Przypomnij później\n"
                          "Zapytam ponownie przy następnym uruchomieniu."),
                nd.Button(BTN_SKIP,
                          "Pomiń tę wersję\n"
                          f"Nie pokazuj tego komunikatu dla wersji {info.version}."),
            ],
            common_buttons=nd.TDCBF_CLOSE,
            expanded=info.notes,
            expanded_label="Co nowego w tej wersji",
            footer=f"Źródło: github.com/{GITHUB_OWNER}/{GITHUB_REPO}",
            icon=nd.ICON_INFO,
            parent_hwnd=self._hwnd(),
            default_id=BTN_DOWNLOAD,
        )

        if pressed is None:                        # brak okna systemowego
            pressed = self._fallback_ask(info)

        if pressed == BTN_DOWNLOAD:
            QDesktopServices.openUrl(QUrl(info.download_url))
            self._info(
                "Pobieranie nowej wersji",
                "Otworzyłem stronę pobierania w przeglądarce.\n\n"
                "Zamknij Mathloader, zanim uruchomisz instalator.")
        elif pressed == BTN_SKIP:
            self._config.skip_version = info.version
            self._config.save()

    def _fallback_ask(self, info: UpdateInfo) -> int:
        """Gdy TaskDialog niedostępny: zwykły MessageBox, a poza Windows — Qt."""
        text = (f"Dostępna jest nowa wersja aplikacji: {info.version}\n"
                f"(używasz {APP_VERSION}).\n\nPobrać ją teraz?")
        result = nd.message_box(
            title=DIALOG_TITLE, text=text,
            flags=nd.MB_YESNO | nd.MB_ICONINFORMATION,
            parent_hwnd=self._hwnd())
        if result is not None:
            return BTN_DOWNLOAD if result == nd.ID_YES else BTN_LATER

        box = QMessageBox(self._window)
        box.setWindowTitle(DIALOG_TITLE)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("Dostępna nowa wersja aplikacji")
        box.setInformativeText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.No)
        answer = box.exec()
        return (BTN_DOWNLOAD if answer == QMessageBox.StandardButton.Yes
                else BTN_LATER)

    def _info(self, heading: str, content: str, *, icon: int = nd.ICON_INFO) -> None:
        """Prosty komunikat — systemowy, a w ostateczności Qt."""
        pressed = nd.task_dialog(
            title=DIALOG_TITLE, heading=heading, content=content,
            common_buttons=nd.TDCBF_OK, icon=icon,
            parent_hwnd=self._hwnd())
        if pressed is not None:
            return

        flags = (nd.MB_ICONWARNING if icon == nd.ICON_WARNING
                 else nd.MB_ICONINFORMATION)
        if nd.message_box(title=DIALOG_TITLE, text=f"{heading}\n\n{content}",
                          flags=nd.MB_OK | flags,
                          parent_hwnd=self._hwnd()) is not None:
            return

        box = QMessageBox(self._window)
        box.setWindowTitle(DIALOG_TITLE)
        box.setIcon(QMessageBox.Icon.Warning if icon == nd.ICON_WARNING
                    else QMessageBox.Icon.Information)
        box.setText(heading)
        box.setInformativeText(content)
        box.exec()
