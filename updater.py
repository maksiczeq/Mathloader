"""
Mathloader — sprawdzanie aktualizacji przez GitHub Releases.

Czysta logika, bez Qt (warstwa okienkowa siedzi w `qtui/updates.py`):
pobiera opis najnowszego wydania, porównuje numer wersji z `APP_VERSION`
i zwraca dane potrzebne do pokazania komunikatu.

Dlaczego endpoint `/releases/latest`, a nie lista tagów: pomija szkice
(draft) i wydania wstępne (pre-release), więc testowe wydanie nie wyskoczy
użytkownikom jako „nowa wersja”.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import requests

from version import (
    APP_NAME, APP_VERSION, is_repo_configured, latest_release_api, releases_page,
)

TIMEOUT_S = 8
NOTES_LIMIT = 1200               # dłuższy changelog i tak nie zmieści się w okienku

_VER_RE = re.compile(r"(\d+(?:\.\d+)*)")


class UpdateError(RuntimeError):
    """Nie udało się sprawdzić aktualizacji (sieć, limit API, brak wydań)."""


@dataclass(frozen=True)
class UpdateInfo:
    """Opis wydania dostępnego na GitHubie."""

    version: str          # „3.1.0” — już bez prefiksu „v”
    notes: str            # treść opisu wydania (changelog), przycięta
    page_url: str         # strona wydania na GitHubie
    download_url: str     # bezpośredni link do instalatora (lub strona wydania)
    published: str        # „2026-09-15” albo pusty ciąg


# ── porównywanie wersji ──────────────────────────────────────────────────────

def parse_version(text: str) -> tuple[int, ...]:
    """„v3.1.0-beta” → (3, 1, 0). Pusta krotka, gdy nie ma czego porównywać."""
    match = _VER_RE.search(text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(remote: str, local: str) -> bool:
    """True, gdy `remote` to wyższy numer niż `local` („3.1” > „3.0.9”)."""
    rem, loc = parse_version(remote), parse_version(local)
    if not rem:
        return False
    length = max(len(rem), len(loc))
    rem += (0,) * (length - len(rem))
    loc += (0,) * (length - len(loc))
    return rem > loc


# ── pobranie danych z GitHuba ────────────────────────────────────────────────

def _pick_asset(assets: list[dict[str, Any]]) -> str:
    """Wybiera plik do pobrania: instalator > inny .exe > .zip."""
    def rank(asset: dict[str, Any]) -> int:
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe") and "setup" in name:
            return 0
        if name.endswith(".exe"):
            return 1
        if name.endswith(".zip"):
            return 2
        return 3

    usable = [a for a in assets if a.get("browser_download_url") and rank(a) < 3]
    if not usable:
        return ""
    return str(sorted(usable, key=rank)[0]["browser_download_url"])


def fetch_latest() -> UpdateInfo:
    """Zwraca opis najnowszego wydania. Rzuca `UpdateError` przy problemie."""
    if not is_repo_configured():
        raise UpdateError(
            "Adres repozytorium GitHub nie został jeszcze ustawiony "
            "(version.py → GITHUB_OWNER)."
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    }
    try:
        resp = requests.get(latest_release_api(), headers=headers,
                            timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        raise UpdateError(f"Brak połączenia z GitHubem: {exc}") from exc

    if resp.status_code == 404:
        raise UpdateError(
            "W repozytorium nie ma jeszcze żadnego wydania (Release).")
    if resp.status_code == 403:
        raise UpdateError(
            "GitHub chwilowo ogranicza liczbę zapytań. Spróbuj za godzinę.")
    if resp.status_code != 200:
        raise UpdateError(f"GitHub odpowiedział kodem {resp.status_code}.")

    try:
        data = resp.json()
    except ValueError as exc:
        raise UpdateError("Nieczytelna odpowiedź GitHuba.") from exc

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise UpdateError("Wydanie nie ma numeru wersji (brak `tag_name`).")

    notes = str(data.get("body") or "").strip()
    if len(notes) > NOTES_LIMIT:
        notes = notes[:NOTES_LIMIT].rstrip() + "\n…"

    return UpdateInfo(
        version=re.sub(r"^[vV]", "", tag),
        notes=notes,
        page_url=str(data.get("html_url") or releases_page()),
        download_url=(_pick_asset(data.get("assets") or [])
                      or str(data.get("html_url") or releases_page())),
        published=str(data.get("published_at") or "")[:10],
    )


def find_update(current: str = APP_VERSION) -> Optional[UpdateInfo]:
    """Zwraca opis wydania, jeśli jest nowsze od `current`; inaczej None."""
    info = fetch_latest()
    return info if is_newer(info.version, current) else None
