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

from PySide6.QtCore import QObject, Signal

from downloader import (
    LessonResult, Phase1Result, download_image, run_phase1, run_phase2,
)
from updater import find_update


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

    def __init__(self, url: str, config):
        super().__init__()
        self._url = url
        self._config = config

    def _run(self) -> None:
        result = run_phase1(self._url, self._config, on_log=self.log.emit)
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

    def __init__(self, current_version: str):
        super().__init__()
        self._current = current_version

    def _run(self) -> None:
        # UpdateError leci do `failed` przez _safe_run w klasie bazowej.
        self.done.emit(find_update(self._current))
