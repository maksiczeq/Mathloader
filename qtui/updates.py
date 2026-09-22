"""
Mathloader — warstwa okienkowa aktualizacji.

Sama logika sieciowa siedzi w `updater.py`; tutaj jest przebieg widziany przez
użytkownika: komunikat o nowej wersji → pobranie → uruchomienie instalatora →
zamknięcie aplikacji, którą instalator odpala z powrotem.

Komunikat o dostępnej wersji celowo jest oknem SYSTEMOWYM (Win32 TaskDialog),
a nie dialogiem w motywie aplikacji — informacja o aktualizacji ma wyglądać jak
komunikat Windows, żeby użytkownik traktował ją poważnie. Sam postęp pobierania
to już zwykłe okno aplikacji, bo dzieje się w jej środku.

Tryby:
  • automatyczny (start aplikacji) — cisza, gdy brak nowej wersji albo brak sieci
  • ręczny („Sprawdź aktualizacje” w zakładce Info) — zawsze pokazuje wynik

Dlaczego aplikacja zamyka się sama: instalator podmienia pliki, na których stoi
uruchomiony proces. Windows nie pozwoli nadpisać otwartego .exe, więc kolejność
jest jedyna możliwa — najpierw wyjdź, potem instaluj.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMessageBox, QProgressBar, QPushButton, QWidget,
)

import paths
from config import AppConfig
from updater import UpdateInfo
from version import (
    APP_VERSION, GITHUB_OWNER, GITHUB_REPO, is_repo_configured, releases_page,
)
from qtui import native_dialogs as nd
from qtui.theme import PAD_MD, PAD_SM, PAD_XL
from qtui.widgets import BaseDialog, hbox, label, vbox
from qtui.workers import DownloadUpdateJob, UpdateJob

DIALOG_TITLE = "Mathloader — aktualizacja"

BTN_DOWNLOAD = 101
BTN_LATER = 102
BTN_SKIP = 103

START_DELAY_MS = 1800          # daj oknu wstać, zanim wyskoczy komunikat
LAUNCH_CHECK_MS = 1500         # ile czekamy, czy instalator w ogóle wystartował
QUIT_DELAY_MS = 400            # chwila na domknięcie okna przed wyjściem


def _mb(value: int) -> str:
    """Bajty → „149,3 MB” (z przecinkiem, bo to polski interfejs)."""
    return f"{value / (1024 * 1024):.1f}".replace(".", ",") + " MB"


class UpdateProgressDialog(BaseDialog):
    """Postęp pobierania nowej wersji.

    Okno jest modalne świadomie: aktualizacja kończy się zamknięciem aplikacji,
    więc użytkownik nie powinien w tym czasie zaczynać pobierania lekcji, które
    i tak zostałoby przerwane w połowie.
    """

    cancelled = Signal()

    def __init__(self, parent: Optional[QWidget], version: str):
        super().__init__(parent, DIALOG_TITLE, width=470)
        lay = vbox(self, m=PAD_XL, s=PAD_MD)

        lay.addWidget(label(f"Aktualizacja do wersji {version}", "DialogTitle"))

        self.stage = label("Pobieranie…", "Hint", wrap=True)
        lay.addWidget(self.stage)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)            # na start tryb nieokreślony
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)

        self.detail = label("", "Muted")
        lay.addWidget(self.detail)
        lay.addSpacing(PAD_SM)

        row = QWidget(self)
        rl = hbox(row, s=PAD_MD)
        rl.addStretch(1)
        self.cancel_btn = QPushButton("Anuluj", row)
        self.cancel_btn.setObjectName("CardAction")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setMinimumWidth(120)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        rl.addWidget(self.cancel_btn)
        lay.addWidget(row)

    # ── postęp ──

    def set_progress(self, done: int, total: int, speed: float) -> None:
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))
            text = f"{_mb(done)} z {_mb(total)}"
        else:
            text = _mb(done)
        if speed > 0:
            text += f"   •   {_mb(int(speed))}/s"
        self.detail.setText(text)

    def set_stage(self, text: str, *, busy: bool = False) -> None:
        self.stage.setText(text)
        if busy:
            self.bar.setRange(0, 0)        # „coś się dzieje”, bez procentów
            self.detail.setText("")

    def lock(self) -> None:
        """Od uruchomienia instalatora nie ma już czego anulować."""
        self.cancel_btn.setEnabled(False)

    # Zamknięcie krzyżykiem albo Esc traktujemy jak „Anuluj”.
    def reject(self) -> None:              # noqa: D102
        self.cancelled.emit()
        super().reject()


class UpdateChecker(QObject):
    """Sprawdza wydania na GitHubie, pobiera je i uruchamia instalator."""

    def __init__(self, window: QWidget, config: AppConfig):
        super().__init__(window)
        self._window = window
        self._config = config
        # Referencji na zadanie NIE zwalniamy w slocie `done` — wątek roboczy
        # wysyła jeszcze `finished`, a sprzątnięty obiekt nie miałby dokąd.
        # Zwalnia ją dopiero kolejne sprawdzenie, podmieniając obiekt.
        self._job: Optional[UpdateJob] = None
        self._download: Optional[DownloadUpdateJob] = None
        self._dialog: Optional[UpdateProgressDialog] = None
        self._busy = False
        self._manual = False
        self._started_at = 0.0

    # ────────────────────────────── uruchomienie

    def check_on_start(self) -> None:
        """Cichy test przy starcie — z opóźnieniem, żeby nie zasłonić okna."""
        paths.cleanup_update_cache()
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
        self._job = UpdateJob(APP_VERSION, portable=paths.is_portable())
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

    def _can_auto_install(self, info: UpdateInfo) -> bool:
        """Czy da się zaktualizować bez udziału użytkownika.

        Warunki: aplikacja pochodzi z instalatora (a nie z ZIP-a ani z kodu
        źródłowego) i wydanie ma instalator do pobrania. Wersja portable to
        zwykły folder — podmiana plików pod działającym programem to zupełnie
        inna operacja, więc tam zostaje droga przez przeglądarkę.
        """
        return (info.is_installer and bool(info.download_url)
                and paths.is_installed())

    def _show_update(self, info: UpdateInfo) -> None:
        auto = self._can_auto_install(info)
        when = f" (wydana {info.published})" if info.published else ""
        size = f"  Rozmiar: {_mb(info.asset_size)}." if info.asset_size else ""

        if auto:
            content = (
                f"Używasz wersji {APP_VERSION}, a dostępna jest wersja "
                f"{info.version}{when}.\n\n"
                f"Mathloader pobierze ją sam, zamknie się na chwilę i wróci "
                f"już zaktualizowany.{size} Ustawienia i historia lekcji "
                f"zostaną zachowane."
            )
            download_btn = nd.Button(
                BTN_DOWNLOAD,
                f"Pobierz i zainstaluj wersję {info.version}\n"
                "Aktualizacja przebiegnie automatycznie.")
        else:
            content = (
                f"Używasz wersji {APP_VERSION}, a dostępna jest wersja "
                f"{info.version}{when}.\n\n"
                "Pobranie otworzy stronę GitHuba w przeglądarce. Instalator "
                "nadpisze obecną wersję — ustawienia i historia lekcji zostaną "
                "zachowane."
            )
            download_btn = nd.Button(
                BTN_DOWNLOAD,
                f"Pobierz wersję {info.version}\n"
                "Otwiera stronę pobierania w przeglądarce.")

        pressed = nd.task_dialog(
            title=DIALOG_TITLE,
            heading="Dostępna nowa wersja aplikacji",
            content=content,
            buttons=[
                download_btn,
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
            if auto:
                self._start_update(info)
            else:
                self._open_page(info)
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

    def _open_page(self, info: UpdateInfo) -> None:
        """Droga ręczna — przeglądarka i instrukcja."""
        QDesktopServices.openUrl(QUrl(info.download_url or info.page_url))
        if paths.is_portable():
            self._info(
                "Pobieranie nowej wersji",
                "Otworzyłem stronę pobierania w przeglądarce.\n\n"
                "Wersję portable aktualizuje się ręcznie: rozpakuj nowy ZIP do "
                "nowego folderu i przenieś do niego podfolder „data” ze starej "
                "wersji — wtedy zachowasz ustawienia i numerację lekcji.")
        else:
            self._info(
                "Pobieranie nowej wersji",
                "Otworzyłem stronę pobierania w przeglądarce.\n\n"
                "Zamknij Mathloader, zanim uruchomisz instalator.")

    # ────────────────────────────── automatyczna aktualizacja

    def _start_update(self, info: UpdateInfo) -> None:
        """Pobiera instalator i po weryfikacji uruchamia go po cichu."""
        if getattr(self._window, "is_busy", lambda: False)():
            self._info(
                "Trwa pobieranie lekcji",
                "Aktualizacja zamyka aplikację, więc przerwałaby pobieranie "
                "w połowie. Poczekaj, aż lekcja się zapisze, i spróbuj "
                "ponownie z zakładki „Info”.",
                icon=nd.ICON_WARNING)
            return

        dest = paths.update_cache_dir() / (info.asset_name
                                           or f"Mathloader-{info.version}-Setup.exe")
        paths.cleanup_update_cache(keep=dest)

        self._dialog = UpdateProgressDialog(self._window, info.version)
        self._dialog.cancelled.connect(self._cancel_download)
        self._dialog.show()

        # Sprawdzenie sumy i rozpoznanie już pobranego pliku robi samo zadanie —
        # jedno i drugie potrafi potrwać sekundy, a okno ma w tym czasie żyć.
        self._started_at = time.monotonic()
        job = DownloadUpdateJob(
            info.download_url, dest,
            checksum_url=info.checksum_url,
            expected_size=info.asset_size)
        # Każdy sygnał niesie swoje zadanie. Anulowane pobieranie kończy się
        # chwilę po kliknięciu „Anuluj" i bez tego jego spóźniony `done`
        # zamknąłby okno kolejnej, dopiero zaczętej próby.
        job.progress.connect(lambda d, t, j=job: self._on_progress(j, d, t))
        job.done.connect(lambda path, j=job: self._on_downloaded(j, path, info))
        job.failed.connect(lambda msg, j=job: self._on_download_failed(j, msg))
        self._download = job
        job.start()

    def _is_current(self, job: DownloadUpdateJob) -> bool:
        return job is self._download

    def _on_progress(self, job: DownloadUpdateJob, done: int, total: int) -> None:
        if self._dialog is None or not self._is_current(job):
            return
        elapsed = max(0.001, time.monotonic() - self._started_at)
        self._dialog.set_progress(done, total, done / elapsed)

    def _cancel_download(self) -> None:
        if self._download is not None:
            self._download.cancel()
        self._dialog = None

    def _on_download_failed(self, job: DownloadUpdateJob, message: str) -> None:
        if not self._is_current(job):
            return
        self._close_dialog()
        self._fail("Nie udało się pobrać aktualizacji", message)

    def _on_downloaded(self, job: DownloadUpdateJob, path: Optional[Path],
                       info: UpdateInfo) -> None:
        if not self._is_current(job):
            return
        if path is None:                     # anulowane przez użytkownika
            self._close_dialog()
            return
        self._install(path, info)

    # ────────────────────────────── instalacja

    def _installer_command(self, installer: Path) -> list[str]:
        """Parametry cichej instalacji.

        `/SILENT` (a nie `/VERYSILENT`) zostawia pasek postępu instalatora —
        przy 500 MB rozpakowania użytkownik przez kilkadziesiąt sekund widzi
        wtedy, że coś się dzieje, zamiast pustego pulpitu po zniknięciu
        aplikacji. Z tego samego powodu NIE tłumimy komunikatów o błędach.

        `WAITPID` każe instalatorowi poczekać, aż nasz proces naprawdę
        zniknie — dopiero wtedy wolno mu nadpisać pliki, na których stoimy.
        """
        log = paths.update_cache_dir() / "instalacja.log"
        args = [
            str(installer),
            "/SILENT", "/NORESTART",
            "/RESTARTAPP=1",
            f"/WAITPID={os.getpid()}",
            f"/LOG={log}",
            f"/DIR={paths.app_dir()}",
        ]
        scope = paths.installed_scope()
        if scope == "user":
            args.append("/CURRENTUSER")
        elif scope == "machine":
            args.append("/ALLUSERS")
        return args

    def _install(self, installer: Path, info: UpdateInfo) -> None:
        if self._dialog is not None:
            self._dialog.lock()
            self._dialog.set_stage(
                "Uruchamiam instalator — Mathloader zamknie się na chwilę "
                "i wróci w nowej wersji.", busy=True)

        try:
            process = subprocess.Popen(
                self._installer_command(installer),
                close_fds=True,
                creationflags=(subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NEW_PROCESS_GROUP),
            )
        except OSError as exc:
            self._close_dialog()
            self._fail("Nie udało się uruchomić instalatora", str(exc))
            return

        # Odmowa zgody UAC albo blokada antywirusa kończy instalator od razu.
        # Lepiej to wychwycić, niż zamknąć aplikację i zostawić użytkownika
        # z niczym.
        QTimer.singleShot(LAUNCH_CHECK_MS, lambda: self._after_launch(process))

    def _after_launch(self, process: subprocess.Popen) -> None:
        code = process.poll()
        if code is not None and code != 0:
            self._close_dialog()
            self._fail(
                "Aktualizacja nie została wykonana",
                "Instalator zakończył się przed czasem — najczęściej znaczy "
                "to, że odmówiono zgody systemu Windows albo zablokował go "
                f"program antywirusowy. (Kod wyjścia: {code}.)")
            return
        QTimer.singleShot(QUIT_DELAY_MS, self._quit)

    def _quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ────────────────────────────── drobiazgi

    def _close_dialog(self) -> None:
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None

    def _fail(self, heading: str, reason: str) -> None:
        """Automat zawiódł — powiedz dlaczego i otwórz drogę ręczną.

        Strona wydania otwiera się dopiero PO komunikacie i jest w nim
        zapowiedziana: przeglądarka wyskakująca bez słowa wyjaśnienia
        wygląda jak kolejna awaria, a nie jak pomoc.
        """
        self._info(
            heading,
            f"{reason}\n\n"
            "Otwieram stronę wydania — stamtąd pobierzesz i zainstalujesz "
            "aktualizację ręcznie.",
            icon=nd.ICON_WARNING)
        QDesktopServices.openUrl(QUrl(releases_page()))

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
