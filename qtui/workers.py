"""
Mathloader — praca w tle (Qt).

Backend (`downloader.py`) jest blokujący, więc uruchamiamy go w zwykłym
`threading.Thread` (daemon). Wyniki wracają przez sygnały `QObject`: obiekt
zadania żyje w wątku głównym, więc `emit()` z wątku roboczego jest przez Qt
kolejkowany i slot wykonuje się bezpiecznie w wątku GUI.

Strona wywołująca MUSI trzymać referencję na obiekcie zadania (inaczej GC
sprzątnie go w trakcie).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from downloader import (
    LessonResult, Phase1Result, download_image, run_phase1, run_phase2,
    run_phase2_append,
)
from updater import (
    DownloadCancelled, UpdateError, download_asset, fetch_checksum,
    find_update,
)


class _Job(QObject):
    log = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def start(self) -> None:
        threading.Thread(target=self._safe_run, daemon=True).start()

    def _safe_run(self) -> None:
        try:
            self._run()
        except Exception as e:          # noqa: BLE001 — pokaż użytkownikowi
            self.failed.emit(str(e))
        finally:
            self.finished.emit()

    def _run(self) -> None:             # nadpisywane
        raise NotImplementedError


class Phase1Job(_Job):
    """Skanowanie strony: Playwright + zebranie URL-i obrazów."""

    done = Signal(object)              # Phase1Result

    def __init__(self, url: str, config, append_lesson: dict | None = None):
        super().__init__()
        self._url = url
        self._config = config
        self._append_lesson = append_lesson

    def _run(self) -> None:
        result = run_phase1(self._url, self._config, on_log=self.log.emit,
                            append_lesson=self._append_lesson)
        self.done.emit(result)


class Phase2Job(_Job):
    """Pobranie i zapis wszystkich obrazów lekcji."""

    progress = Signal(float)
    done = Signal(object)             # LessonResult

    def __init__(self, url: str, topic: str, phase1: Phase1Result, config):
        super().__init__()
        self._url = url
        self._topic = topic
        self._phase1 = phase1
        self._config = config

    def _run(self) -> None:
        result = run_phase2(
            url=self._url, topic=self._topic, phase1=self._phase1,
            config=self._config, on_log=self.log.emit,
            on_progress=self.progress.emit,
        )
        self.done.emit(result)


class Phase2AppendJob(_Job):
    """Dopisanie obrazów do folderu lekcji pobranej wcześniej."""

    progress = Signal(float)
    done = Signal(object)             # LessonResult

    def __init__(self, url: str, lesson: dict, phase1: Phase1Result, config):
        super().__init__()
        self._url = url
        self._lesson = lesson
        self._phase1 = phase1
        self._config = config

    def _run(self) -> None:
        result = run_phase2_append(
            url=self._url, lesson=self._lesson, phase1=self._phase1,
            config=self._config, on_log=self.log.emit,
            on_progress=self.progress.emit,
        )
        self.done.emit(result)


class ImageJob(_Job):
    """Pobranie pojedynczego obrazu do podglądu galerii."""

    done = Signal(int, object)        # idx, bytes|None

    def __init__(self, idx: int, url: str, headers: dict):
        super().__init__()
        self._idx = idx
        self._url = url
        self._headers = headers

    def _run(self) -> None:
        try:
            data = download_image(self._url, headers=self._headers)
        except Exception:              # noqa: BLE001
            data = None
        self.done.emit(self._idx, data)


class UpdateJob(_Job):
    """Zapytanie do GitHuba o najnowsze wydanie (zwykłe HTTP, bez blokowania GUI)."""

    done = Signal(object)             # UpdateInfo | None (None = brak nowszej)

    def __init__(self, current_version: str, *, portable: bool = False):
        super().__init__()
        self._current = current_version
        self._portable = portable

    def _run(self) -> None:
        # UpdateError leci do `failed` przez _safe_run w klasie bazowej.
        self.done.emit(find_update(self._current, portable=self._portable))


class DownloadUpdateJob(_Job):
    """Ściąganie instalatora nowej wersji (~150 MB) poza wątkiem GUI."""

    progress = Signal(int, int)       # pobrane, całość (bajty)
    done = Signal(object)             # Path do pliku albo None przy anulowaniu

    def __init__(self, url: str, dest: Path, *, checksum_url: str = "",
                 expected_size: int = 0):
        super().__init__()
        self._url = url
        self._dest = dest
        self._checksum_url = checksum_url
        self._size = expected_size
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Prosi wątek o przerwanie; plik `.part` zostaje do wznowienia."""
        self._cancel.set()

    def _run(self) -> None:
        # Suma kontrolna leci tym samym wątkiem co pobieranie: to zapytanie
        # sieciowe i przy zerwanym łączu potrafi wisieć kilka sekund, a wątek
        # GUI musi w tym czasie odrysowywać pasek postępu.
        try:
            expected = fetch_checksum(self._checksum_url)
        except UpdateError:
            expected = ""             # brak sumy nie blokuje aktualizacji

        try:
            path = download_asset(
                self._url, self._dest,
                on_progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=self._cancel.is_set,
                expected_size=self._size,
                expected_sha256=expected,
            )
        except DownloadCancelled:
            self.done.emit(None)      # anulowanie to nie błąd
            return
        self.done.emit(path)
