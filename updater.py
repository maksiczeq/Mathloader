"""
Mathloader — sprawdzanie i pobieranie aktualizacji przez GitHub Releases.

Czysta logika, bez Qt (warstwa okienkowa siedzi w `qtui/updates.py`):
pobiera opis najnowszego wydania, porównuje numer wersji z `APP_VERSION`,
ściąga artefakt i sprawdza jego sumę kontrolną.

Dlaczego endpoint `/releases/latest`, a nie lista tagów: pomija szkice
(draft) i wydania wstępne (pre-release), więc testowe wydanie nie wyskoczy
użytkownikom jako „nowa wersja”.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests

from version import (
    APP_NAME, APP_VERSION, is_repo_configured, latest_release_api, releases_page,
)

TIMEOUT_S = 8
NOTES_LIMIT = 1200               # dłuższy changelog i tak nie zmieści się w okienku

# Pobieranie: instalator waży ~150 MB, więc czytamy dużymi kawałkami, a postęp
# raportujemy z częstotliwością wystarczającą dla oka, a nie dla kolejki Qt.
DOWNLOAD_CHUNK = 256 * 1024
PROGRESS_INTERVAL_S = 0.2
DOWNLOAD_TIMEOUT = (10, 60)      # (połączenie, cisza w strumieniu)

# Skąd wolno pobrać plik, który zaraz URUCHOMIMY. Adres przychodzi z odpowiedzi
# GitHuba, ale samo to nie wystarcza: sprawdzamy też, gdzie kończy się łańcuch
# przekierowań, bo to dopiero ten host wysyła nam bajty.
_TRUSTED_HOSTS = frozenset({"github.com", "www.github.com", "api.github.com"})
_TRUSTED_SUFFIX = ".githubusercontent.com"

_VER_RE = re.compile(r"(\d+(?:\.\d+)*)")
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


class UpdateError(RuntimeError):
    """Nie udało się sprawdzić albo pobrać aktualizacji."""


class DownloadCancelled(Exception):
    """Użytkownik przerwał pobieranie — to nie jest błąd."""


@dataclass(frozen=True)
class UpdateInfo:
    """Opis wydania dostępnego na GitHubie."""

    version: str          # „3.1.0” — już bez prefiksu „v”
    notes: str            # treść opisu wydania (changelog), przycięta
    page_url: str         # strona wydania na GitHubie
    download_url: str     # bezpośredni link do artefaktu (lub strona wydania)
    published: str        # „2026-09-15” albo pusty ciąg
    asset_name: str = ""  # nazwa pliku, np. „Mathloader-3.2.1-Setup.exe”
    asset_size: int = 0   # rozmiar w bajtach (0 = nieznany)
    checksum_url: str = ""    # link do pliku .sha256 obok artefaktu
    is_installer: bool = False    # czy artefakt to instalator (a nie ZIP)


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

def _is_trusted(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _TRUSTED_HOSTS or host.endswith(_TRUSTED_SUFFIX)


def _ensure_trusted(url: str) -> None:
    if not _is_trusted(url):
        raise UpdateError(
            f"Odmawiam pobrania pliku spoza GitHuba: {urlparse(url).hostname}")


def _rank_asset(name: str, *, portable: bool) -> int:
    """Im mniej, tym lepiej. Wersja portable potrzebuje ZIP-a, nie instalatora."""
    low = name.lower()
    if portable:
        return 0 if low.endswith(".zip") else 9
    if low.endswith(".exe") and "setup" in low:
        return 0
    if low.endswith(".exe"):
        return 1
    if low.endswith(".zip"):
        return 2
    return 9


def _pick_asset(assets: list[dict[str, Any]], *,
                portable: bool = False) -> Optional[dict[str, Any]]:
    """Wybiera artefakt pasujący do tego sposobu instalacji."""
    usable = [a for a in assets
              if a.get("browser_download_url")
              and _rank_asset(str(a.get("name", "")), portable=portable) < 9]
    if not usable:
        return None
    return sorted(usable,
                  key=lambda a: _rank_asset(str(a.get("name", "")),
                                            portable=portable))[0]


def _find_checksum(assets: list[dict[str, Any]], asset_name: str) -> str:
    """Link do `<nazwa artefaktu>.sha256`, jeśli wydanie takowy zawiera."""
    wanted = f"{asset_name}.sha256".lower()
    for asset in assets:
        if str(asset.get("name", "")).lower() == wanted:
            return str(asset.get("browser_download_url") or "")
    return ""


def fetch_latest(*, portable: bool = False) -> UpdateInfo:
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

    assets = data.get("assets") or []
    page_url = str(data.get("html_url") or releases_page())
    asset = _pick_asset(assets, portable=portable)
    name = str(asset.get("name", "")) if asset else ""

    return UpdateInfo(
        version=re.sub(r"^[vV]", "", tag),
        notes=notes,
        page_url=page_url,
        download_url=(str(asset["browser_download_url"]) if asset else page_url),
        published=str(data.get("published_at") or "")[:10],
        asset_name=name,
        asset_size=int(asset.get("size") or 0) if asset else 0,
        checksum_url=_find_checksum(assets, name) if name else "",
        is_installer=bool(name) and name.lower().endswith(".exe"),
    )


def find_update(current: str = APP_VERSION, *,
                portable: bool = False) -> Optional[UpdateInfo]:
    """Zwraca opis wydania, jeśli jest nowsze od `current`; inaczej None."""
    info = fetch_latest(portable=portable)
    return info if is_newer(info.version, current) else None


# ── pobieranie artefaktu ─────────────────────────────────────────────────────

def fetch_checksum(url: str) -> str:
    """Wyciąga sumę SHA-256 z pliku `.sha256` (format: „<suma>  <nazwa>”)."""
    if not url:
        return ""
    _ensure_trusted(url)
    try:
        resp = requests.get(url, timeout=TIMEOUT_S,
                            headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateError(f"Nie udało się pobrać sumy kontrolnej: {exc}") from exc
    match = _SHA256_RE.search(resp.text or "")
    return match.group(1).lower() if match else ""


def sha256_of(path: Path) -> str:
    """Suma SHA-256 pliku, liczona kawałkami (plik ma ~150 MB)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def have_complete_file(path: Path, *, expected_size: int = 0,
                       expected_sha256: str = "") -> bool:
    """Czy `path` to już gotowy, ten sam plik (a nie urwana połówka).

    Bez żadnego punktu odniesienia odpowiadamy „nie": lepiej pobrać drugi raz,
    niż uruchomić instalator, o którym nic nie wiemy.
    """
    try:
        if not path.is_file():
            return False
        if expected_sha256:
            return sha256_of(path).lower() == expected_sha256.lower()
        if expected_size:
            return path.stat().st_size == expected_size
    except OSError:
        return False
    return False


def download_asset(
    url: str,
    dest: Path,
    *,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    expected_size: int = 0,
    expected_sha256: str = "",
) -> Path:
    """Pobiera plik do `dest`, wznawiając przerwane pobranie.

    Ściąga do pliku `.part` i dopiero gotowy podmienia pod właściwą nazwę —
    dzięki temu pod `dest` nigdy nie leży urwana połówka instalatora, którą
    ktoś mógłby uruchomić. Przerwane pobranie zostaje jako `.part` i przy
    kolejnym podejściu dociąga się nagłówkiem `Range`, zamiast lecieć od zera.

    `should_cancel` sprawdzamy między kawałkami — po anulowaniu leci
    `DownloadCancelled`, a `.part` zostaje na dysku.
    """
    _ensure_trusted(url)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Plik z poprzedniego podejścia (aplikację zamknięto przed instalacją)
    # nadaje się do użycia od razu — o ile to ten sam plik.
    if have_complete_file(dest, expected_size=expected_size,
                          expected_sha256=expected_sha256):
        if on_progress:
            size = dest.stat().st_size
            on_progress(size, size)
        return dest
    dest.unlink(missing_ok=True)

    part = dest.with_name(dest.name + ".part")

    have = part.stat().st_size if part.exists() else 0
    headers = {
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        "Accept": "application/octet-stream",
    }
    if have:
        headers["Range"] = f"bytes={have}-"

    try:
        resp = requests.get(url, headers=headers, stream=True,
                            timeout=DOWNLOAD_TIMEOUT)
    except requests.RequestException as exc:
        raise UpdateError(f"Pobieranie nie powiodło się: {exc}") from exc

    with resp:
        _ensure_trusted(resp.url)
        if resp.status_code == 416:
            # Mamy więcej bajtów niż plik po drugiej stronie — wydanie zostało
            # podmienione. Zaczynamy od zera zamiast sklejać dwie różne wersje.
            part.unlink(missing_ok=True)
            raise UpdateError(
                "Pobrany wcześniej plik nie pasuje do tego wydania. "
                "Spróbuj jeszcze raz.")
        if resp.status_code not in (200, 206):
            raise UpdateError(f"Serwer odpowiedział kodem {resp.status_code}.")
        if resp.status_code == 200:
            have = 0                       # serwer zignorował Range — od nowa

        total = int(resp.headers.get("Content-Length") or 0) + have
        done = have
        last_report = 0.0

        try:
            with open(part, "ab" if have else "wb") as f:
                for chunk in resp.iter_content(DOWNLOAD_CHUNK):
                    if should_cancel is not None and should_cancel():
                        raise DownloadCancelled
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if on_progress and now - last_report >= PROGRESS_INTERVAL_S:
                        last_report = now
                        on_progress(done, total)
        except requests.RequestException as exc:
            raise UpdateError(f"Pobieranie przerwane: {exc}") from exc

    if on_progress:
        on_progress(done, total or done)

    if total and done != total:
        raise UpdateError(
            f"Pobrano {done} z {total} bajtów — plik jest niekompletny.")

    if expected_sha256:
        actual = sha256_of(part)
        if actual.lower() != expected_sha256.lower():
            part.unlink(missing_ok=True)
            raise UpdateError(
                "Suma kontrolna pobranego pliku się nie zgadza — "
                "plik mógł zostać uszkodzony po drodze. Spróbuj ponownie.")

    os.replace(part, dest)
    return dest
