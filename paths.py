"""
Mathloader — ustalanie ścieżek danych i zasobów.

Rozróżnia trzy tryby uruchomienia:
  • deweloperski  — kod źródłowy; dane leżą w katalogu projektu (jak dotąd)
  • zainstalowany — exe w Program Files; dane w %APPDATA%\\Mathloader
  • portable      — exe + plik-znacznik `portable.txt`; dane w podfolderze `data`

Dlaczego to istnieje: katalog instalacyjny (Program Files) jest tylko do odczytu,
a w trybie onefile katalog rozpakowania znika po zamknięciu programu. Zapisywanie
settings.json obok pliku wykonywalnego kończyłoby się crashem albo utratą
konfiguracji przy każdym starcie.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

APP_NAME = "Mathloader"
PORTABLE_MARKER = "portable.txt"


def is_frozen() -> bool:
    """True, gdy aplikacja działa jako zbudowany plik .exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Katalog z plikiem wykonywalnym (frozen) lub z kodem źródłowym (dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """Katalog zasobów dołączonych przez PyInstaller (_internal / _MEIPASS)."""
    mei = getattr(sys, "_MEIPASS", None)
    return Path(mei) if mei else Path(__file__).resolve().parent


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".mathloader_write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def is_portable() -> bool:
    """Tryb portable: znacznik obok exe ORAZ zapisywalny katalog aplikacji."""
    return (is_frozen()
            and (app_dir() / PORTABLE_MARKER).exists()
            and _is_writable(app_dir()))


def data_dir() -> Path:
    """Katalog na settings.json, lessons_history.json i log błędów."""
    if not is_frozen():
        return app_dir()                       # dev: obok kodu, bez zmian
    if is_portable():
        return app_dir() / "data"
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def ensure_data_dir() -> Path:
    d = data_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def settings_file() -> Path:
    return ensure_data_dir() / "settings.json"


def history_file() -> Path:
    return ensure_data_dir() / "lessons_history.json"


def log_file() -> Path:
    return ensure_data_dir() / "mathloader-error.log"


# ── Bezpieczny zapis danych użytkownika ─────────────────────────────────────

def write_json_atomic(path: Path, data: Any) -> None:
    """Zapisuje JSON tak, żeby przerwanie zapisu nie skasowało poprzedniej wersji.

    Zwykłe `open(path, "w")` najpierw ZERUJE plik — crash, zanik prądu albo
    zamknięcie systemu w trakcie zostawia plik pusty lub ucięty. Przy starcie
    wygląda to dokładnie jak „zniknęła cała historia lekcji”. Dlatego zapis
    idzie do pliku obok i dopiero `os.replace()` (na NTFS atomowe) podmienia
    całość jednym ruchem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        # Nieudany zapis nie może zostawiać po sobie połówki pliku w katalogu
        # danych — oryginał i tak jest nietknięty.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def quarantine_broken(path: Path) -> Optional[Path]:
    """Odsuwa nieczytelny plik na bok i zwraca nową nazwę (albo None).

    Bez tego uszkodzony JSON zostałby po cichu nadpisany przy najbliższym
    zapisie i dane przepadłyby bezpowrotnie. Tak zostaje kopia do ratowania.
    """
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.uszkodzony-{stamp}{path.suffix}")
    try:
        path.replace(backup)
        return backup
    except OSError:
        return None


def setup_playwright_env() -> None:
    """Wskazuje Playwright na przeglądarkę dołączoną do builda.

    Bez tego zbudowana aplikacja szukałaby Chromium w %LOCALAPPDATA%\\ms-playwright,
    którego użytkownik końcowy nie ma — i każde pobieranie kończyłoby się błędem
    „Executable doesn't exist".
    """
    if not is_frozen():
        return
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return                                 # świadome nadpisanie — nie ruszamy
    for candidate in (bundle_dir() / "ms-playwright", app_dir() / "ms-playwright"):
        if candidate.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
            return
