"""
Mathloader — moduł konfiguracji.

Zarządza plikiem settings.json z ustawieniami użytkownika:
  • Ścieżki zapisu (dowolna liczba kopii)
  • Formaty nazewnictwa folderów i obrazów
  • Parametry scrollowania / timeoutu
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from paths import quarantine_broken, settings_file, write_json_atomic

# Katalog zależy od trybu uruchomienia (dev / zainstalowany / portable) —
# patrz paths.py. W Program Files zapis obok exe byłby niemożliwy.
SETTINGS_FILE = settings_file()

DEFAULT_SETTINGS: dict[str, Any] = {
    "save_paths": [],
    "folder_format": "{nr} Lekcja {temat}",
    "image_format": "{nr}-{img}.jpg",
    "scroll_pause": 1.5,
    "scroll_step": 800,
    "page_timeout_ms": 30000,
    "setup_completed": False,
    # Aktualizacje: czy pytać GitHuba przy starcie i która wersja została
    # świadomie pominięta („Pomiń tę wersję” w komunikacie).
    "check_updates": True,
    "skip_version": "",
    # Motyw: pierwsze uruchomienie zawsze ciemne, potem ostatni wybór.
    "theme": "dark",
    # Historia: czy chować lekcje z wygasłym linkiem (domyślnie widoczne).
    "hide_expired": False,
}

# Dostępne placeholdery z opisami
FOLDER_PLACEHOLDERS: dict[str, str] = {
    "{nr}": "Numer lekcji (1, 2, 3…)",
    "{temat}": "Temat z OCR",
    "{data}": "Data pobrania (YYYY-MM-DD)",
}

IMAGE_PLACEHOLDERS: dict[str, str] = {
    "{nr}": "Numer lekcji",
    "{img}": "Numer obrazu (01, 02…)",
    "{temat}": "Temat lekcji",
}


class AppConfig:
    """Zarządza konfiguracją aplikacji (settings.json)."""

    def __init__(self, settings_file: Path | None = None):
        self._file = settings_file or SETTINGS_FILE
        self._data: dict[str, Any] = dict(DEFAULT_SETTINGS)

    # ── I/O ──

    @property
    def file(self) -> Path:
        """Plik, z którego ta konfiguracja faktycznie czyta i do którego pisze."""
        return self._file

    def load(self) -> "AppConfig":
        """Wczytuje konfigurację z pliku. Zwraca self dla chain-owania."""
        if self._file.exists():
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                self._data.update(stored)
            except json.JSONDecodeError:
                # Uszkodzony plik odkładamy na bok — inaczej pierwszy zapis
                # nadpisałby go ustawieniami domyślnymi i przepadłby na dobre.
                quarantine_broken(self._file)
            except OSError:
                pass
        return self

    def save(self) -> None:
        """Zapisuje konfigurację do pliku (atomowo — patrz paths.py)."""
        write_json_atomic(self._file, self._data)

    def delete_file(self) -> None:
        """Usuwa plik konfiguracji z dysku (reset do ustawień fabrycznych)."""
        try:
            self._file.unlink()
        except OSError:
            pass

    # ── Status ──

    def is_first_run(self) -> bool:
        return not self._data.get("setup_completed", False)

    def mark_setup_complete(self) -> None:
        self._data["setup_completed"] = True
        self.save()

    # ── Właściwości ──

    @property
    def save_paths(self) -> list[Path]:
        return [Path(p) for p in self._data.get("save_paths", [])]

    @save_paths.setter
    def save_paths(self, value: list[str | Path]) -> None:
        self._data["save_paths"] = [str(p) for p in value]

    @property
    def default_save_path(self) -> Path | None:
        """Pierwsza ścieżka z listy — tam zaglądamy najpierw.

        Kolejność ścieżek ustawia użytkownik w Ustawieniach (strzałkami), więc
        „domyślna" to po prostu ta na górze. Historia otwiera folder lekcji
        stamtąd, dzięki czemu odłączony pendrive dalej w kolejce nie zmienia
        tego, gdzie trafia kliknięcie „Otwórz".
        """
        paths = self.save_paths
        return paths[0] if paths else None

    @property
    def folder_format(self) -> str:
        return self._data.get("folder_format", DEFAULT_SETTINGS["folder_format"])

    @folder_format.setter
    def folder_format(self, value: str) -> None:
        self._data["folder_format"] = value

    @property
    def image_format(self) -> str:
        return self._data.get("image_format", DEFAULT_SETTINGS["image_format"])

    @image_format.setter
    def image_format(self, value: str) -> None:
        self._data["image_format"] = value

    @property
    def scroll_pause(self) -> float:
        return float(self._data.get("scroll_pause", 1.5))

    @scroll_pause.setter
    def scroll_pause(self, value: float) -> None:
        self._data["scroll_pause"] = value

    @property
    def scroll_step(self) -> int:
        return int(self._data.get("scroll_step", 800))

    @property
    def page_timeout_ms(self) -> int:
        return int(self._data.get("page_timeout_ms", 30000))

    @page_timeout_ms.setter
    def page_timeout_ms(self, value: int) -> None:
        self._data["page_timeout_ms"] = value

    # ── Aktualizacje ──

    @property
    def check_updates(self) -> bool:
        return bool(self._data.get("check_updates", True))

    @check_updates.setter
    def check_updates(self, value: bool) -> None:
        self._data["check_updates"] = bool(value)

    # ── Wygląd ──

    @property
    def theme(self) -> str:
        """„dark” albo „light”; przy pierwszym uruchomieniu zawsze ciemny."""
        value = str(self._data.get("theme", "dark")).lower()
        return value if value in ("dark", "light") else "dark"

    @theme.setter
    def theme(self, value: str) -> None:
        self._data["theme"] = "light" if str(value).lower() == "light" else "dark"

    # ── Historia ──

    @property
    def hide_expired(self) -> bool:
        """Czy zakładka „Historia” chowa lekcje z wygasłym linkiem."""
        return bool(self._data.get("hide_expired", False))

    @hide_expired.setter
    def hide_expired(self, value: bool) -> None:
        self._data["hide_expired"] = bool(value)

    @property
    def skip_version(self) -> str:
        """Wersja pominięta przez użytkownika — o niej nie przypominamy."""
        return str(self._data.get("skip_version", ""))

    @skip_version.setter
    def skip_version(self, value: str) -> None:
        self._data["skip_version"] = str(value)

    # ── Formatowanie nazw ──

    def format_folder_name(self, lesson_num: int, topic: str, date: str = "") -> str:
        """Buduje nazwę folderu z szablonu użytkownika."""
        if not date:
            date = time.strftime("%Y-%m-%d")
            
        has_topic = topic and topic not in ("Bez_tematu", "*Bez Tematu*")
        topic_str = f"({topic})" if has_topic else ""
        
        try:
            result = self.folder_format.format(nr=lesson_num, temat=topic_str, data=date)
            # Sprzątanie podwójnych spacji
            return " ".join(result.split()).strip()
        except (KeyError, ValueError, IndexError):
            if has_topic:
                return f"{lesson_num} Lekcja ({topic})"
            return f"{lesson_num} Lekcja"

    def format_image_name(self, lesson_num: int, image_num: int, topic: str = "") -> str:
        """Buduje nazwę pliku obrazu z szablonu użytkownika."""
        img_str = f"{image_num:02d}"
        try:
            return self.image_format.format(nr=lesson_num, img=img_str, temat=topic)
        except (KeyError, ValueError, IndexError):
            return f"{lesson_num}-{img_str}.jpg"

    # ── Podglądy (do live preview w GUI) ──

    @staticmethod
    def preview_folder_format(fmt: str) -> str:
        """Zwraca podgląd formatu folderu z przykładowymi danymi."""
        try:
            raw = fmt.format(nr=1, temat="(WIELOMIANY KL.2)", data="2026-09-06")
            return " ".join(raw.split()).strip()
        except (KeyError, ValueError, IndexError):
            return "Błąd formatu"

    @staticmethod
    def preview_image_format(fmt: str) -> str:
        """Zwraca podgląd formatu nazwy obrazu z przykładowymi danymi."""
        try:
            return fmt.format(nr=1, img="01", temat="WIELOMIANY KL.2")
        except (KeyError, ValueError, IndexError):
            return "Błąd formatu"

    # ── Walidacja ──

    def validate(self) -> list[str]:
        """Waliduje konfigurację. Zwraca listę błędów (pusta = OK)."""
        errors: list[str] = []
        if not self._data.get("save_paths"):
            errors.append("Dodaj przynajmniej jedną ścieżkę zapisu.")
        fmt = self.folder_format
        if not fmt.strip():
            errors.append("Format nazwy folderu nie może być pusty.")
        img_fmt = self.image_format
        if "{img}" not in img_fmt:
            errors.append("Format obrazu musi zawierać placeholder {img}.")
        if not img_fmt.strip():
            errors.append("Format nazwy obrazu nie może być pusty.")
        return errors
