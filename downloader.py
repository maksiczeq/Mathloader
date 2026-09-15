"""
Mathloader — moduł backendu.

Cała logika pobierania: Playwright, HTTP, historia lekcji.
Nie zawiera żadnych wywołań input() ani print().
Komunikacja z GUI odbywa się przez callbacki on_log / on_progress.

Architektura dwufazowa:
  Phase 1  →  Playwright: otwórz stronę, scroll, zbierz URL-e obrazów, data lekcji
  Phase 2  →  Pobierz obrazy, zapisz w N folderach, zarejestruj w historii
"""
from __future__ import annotations

import io
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import requests
from PIL import Image
from playwright.sync_api import sync_playwright

from paths import history_file, quarantine_broken, write_json_atomic

# ──────────────────────────────────────────────
# Typy
# ──────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    """Usuwa znaki niedozwolone w nazwach plików Windows."""
    sanitized = re.sub(r'[\\/:*?"<>|]', "", name)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized[:200] if sanitized else "*Bez Tematu*"

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]  # 0.0 – 1.0

HISTORY_FILE = history_file()

# Strona lekcji pokazuje czas w strefie serwera — o 2 h wstecz względem czasu
# lokalnego (PL). Dodajemy offset, żeby data utworzenia była realna.
PAGE_TZ_OFFSET_HOURS = 2
# Link do lekcji na serwerze przestaje działać po tygodniu od utworzenia.
LINK_EXPIRY_DAYS = 7

_HISTORY_TS_FMT = "%Y-%m-%d %H:%M:%S"
_DATETIME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T]+(\d{1,2}):(\d{2}):(\d{2})")
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2}):(\d{2})\b")

# Aplikacja pobiera lekcje WYŁĄCZNIE z tego serwera i tej ścieżki.
SUPPORTED_URL_HINT = "http://sw.syrjb.com:8081/view/oss/viewDocument/[…]"
_SUPPORTED_URL_RE = re.compile(
    r"^\s*https?://sw\.syrjb\.com(?::\d+)?/view/oss/viewDocument/[^\s/?#]+/?\s*$",
    re.IGNORECASE,
)


def is_supported_url(url: str) -> bool:
    """True, jeśli URL wskazuje na dokument lekcji z obsługiwanego serwera."""
    return bool(url) and _SUPPORTED_URL_RE.match(url) is not None


@dataclass
class Phase1Result:
    """Wynik pierwszej fazy (skanowanie strony + OCR)."""
    image_urls: list[str]
    headers: dict[str, str]
    first_image_bytes: Optional[bytes]
    lesson_number: int
    existing_lesson: Optional[dict]
    lesson_created_at: Optional[str] = None   # "YYYY-MM-DD HH:MM:SS" (czas lokalny)


@dataclass
class LessonResult:
    """Wynik końcowy pobierania lekcji."""
    success: bool
    lesson_number: int
    topic: str
    total_images: int
    downloaded_images: int
    save_results: list[tuple[str, bool, str]] = field(default_factory=list)
    error: Optional[str] = None


# ──────────────────────────────────────────────
# HISTORIA LEKCJI
# ──────────────────────────────────────────────

def load_history() -> dict:
    """Wczytuje historię lekcji z pliku JSON."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            # Uszkodzoną historię odkładamy na bok (plik `.uszkodzony-…`),
            # zamiast pozwolić nadpisać ją pustą przy najbliższym pobraniu.
            quarantine_broken(HISTORY_FILE)
        except OSError:
            pass
    return {"next_number": 1, "last_url": None, "last_topic": None, "lessons": []}


def save_history(history: dict) -> None:
    """Zapisuje historię lekcji do pliku JSON (atomowo — patrz paths.py)."""
    write_json_atomic(HISTORY_FILE, history)


def delete_history() -> None:
    """Usuwa plik historii lekcji z dysku (reset do ustawień fabrycznych)."""
    try:
        HISTORY_FILE.unlink()
    except OSError:
        pass


def find_existing_lesson(history: dict, url: str) -> Optional[dict]:
    """Szuka lekcji w historii po URL-u."""
    for entry in history.get("lessons", []):
        if entry.get("url") == url:
            return {
                "number": entry.get("number", history.get("next_number", 2) - 1),
                "topic": entry.get("topic", ""),
                "downloaded_at": entry.get("downloaded_at", ""),
                "created_at": entry.get("created_at", entry.get("downloaded_at", "")),
            }
    # Zgodność wstecz ze starszym formatem historii (bez listy "lessons").
    if history.get("last_url") == url:
        return {
            "number": history.get("next_number", 2) - 1,
            "topic": history.get("last_topic", ""),
            "downloaded_at": history.get("last_downloaded_at", ""),
            "created_at": history.get("last_downloaded_at", ""),
        }
    return None


def lesson_expiry(lesson: dict) -> Optional[datetime]:
    """Moment wygaśnięcia linku = data utworzenia lekcji + LINK_EXPIRY_DAYS."""
    ref = lesson.get("created_at") or lesson.get("downloaded_at")
    if not ref:
        return None
    try:
        return (datetime.strptime(ref, _HISTORY_TS_FMT)
                + timedelta(days=LINK_EXPIRY_DAYS))
    except (ValueError, TypeError):
        return None


def is_link_expired(lesson: dict) -> bool:
    """True, jeśli minął tydzień od utworzenia lekcji (link nie działa)."""
    exp = lesson_expiry(lesson)
    return exp is not None and datetime.now() >= exp


def get_next_lesson_number(history: dict) -> int:
    """Zwraca kolejny numer lekcji."""
    return history.get("next_number", 1)


def register_lesson(history: dict, url: str, lesson_number: int, topic: str,
                    created_at: Optional[str] = None) -> None:
    """Rejestruje pobraną lekcję: aktualizuje licznik i dopisuje wpis do historii.

    `created_at` — realna data utworzenia lekcji (ze strony); od niej liczone
    jest wygaśnięcie linku. Gdy jej brak, używamy chwili pobrania.
    """
    downloaded_at = time.strftime(_HISTORY_TS_FMT)
    created_at = created_at or downloaded_at

    lessons = history.setdefault("lessons", [])
    existing_entry = next((e for e in lessons if e.get("url") == url), None)

    if existing_entry is None:
        lessons.append({
            "number": lesson_number,
            "url": url,
            "topic": topic,
            "downloaded_at": downloaded_at,
            "created_at": created_at,
        })
        # Licznik przesuwamy tylko dla naprawdę nowej lekcji.
        history["next_number"] = max(history.get("next_number", 1), lesson_number + 1)
    else:
        existing_entry["number"] = lesson_number
        existing_entry["topic"] = topic
        existing_entry["downloaded_at"] = downloaded_at
        existing_entry["created_at"] = created_at

    history["last_url"] = url
    history["last_topic"] = topic
    history["last_downloaded_at"] = downloaded_at
    save_history(history)


def delete_lesson(history: dict, lesson: dict) -> bool:
    """Usuwa pojedynczy wpis lekcji z historii. Zwraca True, jeśli coś usunięto."""
    lessons = history.get("lessons", [])

    def _same(entry: dict) -> bool:
        return (
            entry.get("url") == lesson.get("url")
            and entry.get("number") == lesson.get("number")
            and entry.get("downloaded_at") == lesson.get("downloaded_at")
        )

    remaining = [e for e in lessons if not _same(e)]
    removed = len(remaining) != len(lessons)
    history["lessons"] = remaining

    # Jeśli usunięto lekcję zapamiętaną jako "ostatnia", wyczyść też skrót.
    if removed and history.get("last_url") == lesson.get("url"):
        history["last_url"] = None
        history["last_topic"] = None
        history["last_downloaded_at"] = None

    if removed:
        save_history(history)
    return removed


# ──────────────────────────────────────────────
# POBIERANIE OBRAZÓW
# ──────────────────────────────────────────────

def download_image(url: str, headers: Optional[dict] = None) -> Optional[bytes]:
    """Pobiera obraz z URL-a i zwraca bajty."""
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image" in content_type or url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
        ):
            return resp.content
        # Próba otwarcia jako obraz mimo braku nagłówka
        try:
            Image.open(io.BytesIO(resp.content)).verify()
            return resp.content
        except Exception:
            return None
    except Exception:
        return None


def convert_to_jpeg(image_bytes: bytes) -> bytes:
    """Konwertuje obraz do JPEG (obsługuje PNG/WebP/RGBA)."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    except Exception:
        return image_bytes


def save_image_to_paths(
    image_bytes: bytes,
    filename: str,
    folders: list[Path],
) -> list[tuple[Path, bool, str]]:
    """
    Zapisuje obraz do N folderów.
    Zwraca listę (ścieżka, sukces, komunikat).
    """
    results: list[tuple[Path, bool, str]] = []
    for folder in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            filepath = folder / filename
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            results.append((filepath, True, "OK"))
        except Exception as e:
            results.append((folder / filename, False, str(e)))
    return results


# ──────────────────────────────────────────────
# PLAYWRIGHT — scrollowanie i zbieranie URL-i
# ──────────────────────────────────────────────

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def scroll_to_bottom(
    page,
    scroll_pause: float = 1.5,
    scroll_step: int = 800,
    on_log: Optional[LogCallback] = None,
) -> None:
    """Przewija stronę do dołu, wymuszając lazy-loading."""
    if on_log:
        on_log("Przewijanie strony…")

    previous_height = 0
    stale_count = 0

    while stale_count < 5:
        page.evaluate(f"window.scrollBy(0, {scroll_step})")
        time.sleep(scroll_pause)
        current_height = page.evaluate("document.body.scrollHeight")
        if current_height == previous_height:
            stale_count += 1
        else:
            stale_count = 0
        previous_height = current_height

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    if on_log:
        on_log("Scrollowanie zakończone.")


def extract_lesson_datetime(page) -> Optional[str]:
    """Wyciąga datę+godzinę utworzenia lekcji ze strony i przelicza na czas lokalny.

    Strona zawiera daty w formacie RRRR-MM-DD oraz godziny GG:MM:SS (czas serwera).
    Bierzemy pierwsze pełne wystąpienie i dodajemy PAGE_TZ_OFFSET_HOURS.
    """
    text = ""
    try:
        text = page.inner_text("body")
    except Exception:
        try:
            text = page.evaluate("document.body.innerText || document.body.textContent || ''")
        except Exception:
            text = ""
    if not text:
        return None

    dt: Optional[datetime] = None
    m = _DATETIME_RE.search(text)
    if m:
        y, mo, d, hh, mm, ss = (int(x) for x in m.groups())
        try:
            dt = datetime(y, mo, d, hh % 24, mm, ss)
        except ValueError:
            dt = None
    if dt is None:
        md = _DATE_RE.search(text)
        if md:
            y, mo, d = (int(x) for x in md.groups())
            mt = _TIME_RE.search(text)
            try:
                if mt:
                    hh, mm, ss = (int(x) for x in mt.groups())
                    dt = datetime(y, mo, d, hh % 24, mm, ss)
                else:
                    dt = datetime(y, mo, d)
            except ValueError:
                dt = None
    if dt is None:
        return None

    return (dt + timedelta(hours=PAGE_TZ_OFFSET_HOURS)).strftime(_HISTORY_TS_FMT)


def collect_image_urls(page) -> list[str]:
    """Zbiera unikalne URL-e dużych obrazów ze strony."""
    raw_urls = page.evaluate("""
        () => {
            const imgs = document.querySelectorAll('img');
            const urls = [];
            for (const img of imgs) {
                const src = img.src || img.dataset.src
                            || img.getAttribute('data-lazy-src') || '';
                const w = img.naturalWidth || 0;
                const h = img.naturalHeight || 0;
                if (src && (w > 100 || h > 100 || w === 0)) {
                    urls.push(src);
                }
            }
            return urls;
        }
    """)

    seen: set[str] = set()
    unique: list[str] = []
    for url in raw_urls:
        if url not in seen and url.startswith("http"):
            seen.add(url)
            unique.append(url)
    return unique


# ──────────────────────────────────────────────
# FAZA 1 — skanowanie strony + OCR
# ──────────────────────────────────────────────

def run_phase1(
    url: str,
    config,
    on_log: Optional[LogCallback] = None,
) -> Phase1Result:
    """
    Otwiera stronę, scrolluje, zbiera URL-e obrazów, pobiera
    pierwszy obraz i przepuszcza go przez OCR.
    """
    if not is_supported_url(url):
        raise ValueError(
            f"Nieobsługiwany adres. Wymagany format: {SUPPORTED_URL_HINT}"
        )

    history = load_history()
    existing = find_existing_lesson(history, url)
    # Ponowne pobranie tego samego URL-a zachowuje oryginalny numer lekcji
    # (nie tworzy dziury w numeracji ani duplikatu w historii).
    if existing and existing.get("number"):
        lesson_number = existing["number"]
    else:
        lesson_number = get_next_lesson_number(history)

    if on_log:
        on_log(f"Numer lekcji: {lesson_number}")
        on_log("Uruchamiam przeglądarkę…")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=_USER_AGENT,
        )
        page = context.new_page()

        if on_log:
            on_log(f"Otwieram: {url}")

        try:
            page.goto(
                url, wait_until="networkidle", timeout=config.page_timeout_ms
            )
        except Exception:
            if on_log:
                on_log("Timeout oczekiwania na networkidle — kontynuuję…")

        time.sleep(2)
        scroll_to_bottom(page, config.scroll_pause, config.scroll_step, on_log)

        image_urls = collect_image_urls(page)
        lesson_created_at = extract_lesson_datetime(page)
        if on_log and lesson_created_at:
            on_log(f"Data utworzenia lekcji: {lesson_created_at}")

        # Cookies → header do bezpośredniego HTTP
        cookies = context.cookies()
        cookie_header = "; ".join(
            f"{c['name']}={c['value']}" for c in cookies
        )
        headers: dict[str, str] = {
            "Referer": url,
            "User-Agent": _USER_AGENT,
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        browser.close()

    if not image_urls:
        if on_log:
            on_log("Nie znaleziono żadnych obrazów na stronie!")
        return Phase1Result([], headers, None, lesson_number, existing,
                            lesson_created_at)

    if on_log:
        on_log(f"Znaleziono {len(image_urls)} obrazów.")
        on_log("Pobieranie pierwszego obrazu do podglądu…")

    first_image_bytes = download_image(image_urls[0], headers=headers)

    if not first_image_bytes:
        if on_log:
            on_log("Nie udało się pobrać pierwszego obrazu.")

    return Phase1Result(
        image_urls=image_urls,
        headers=headers,
        first_image_bytes=first_image_bytes,
        lesson_number=lesson_number,
        existing_lesson=existing,
        lesson_created_at=lesson_created_at,
    )


# ──────────────────────────────────────────────
# FAZA 2 — pobieranie i zapis
# ──────────────────────────────────────────────

def run_phase2(
    url: str,
    topic: str,
    phase1: Phase1Result,
    config,
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> LessonResult:
    """
    Pobiera wszystkie obrazy, zapisuje w N folderach,
    rejestruje lekcję w historii.
    """
    lesson_number = phase1.lesson_number
    save_paths = config.save_paths

    folder_name = config.format_folder_name(lesson_number, topic)
    folders = []
    for p in save_paths:
        target_dir = p / folder_name
        copy_num = 2
        while target_dir.exists():
            target_dir = p / f"{folder_name} [{copy_num}]"
            copy_num += 1
        folders.append(target_dir)

    if on_log:
        on_log(f"Folder: {folder_name}")
        for f in folders:
            on_log(f"  → {f}")

    downloaded_count = 0
    total = len(phase1.image_urls)
    all_results: list[tuple[str, bool, str]] = []

    for idx, img_url in enumerate(phase1.image_urls, start=1):
        filename = config.format_image_name(lesson_number, idx, topic)
        if on_log:
            on_log(f"[{idx}/{total}] {filename}")

        # Pierwszy obraz już pobrany w phase1
        if idx == 1 and phase1.first_image_bytes:
            image_bytes: Optional[bytes] = phase1.first_image_bytes
        else:
            image_bytes = download_image(img_url, headers=phase1.headers)

        if image_bytes:
            image_bytes = convert_to_jpeg(image_bytes)
            results = save_image_to_paths(image_bytes, filename, folders)
            for path, success, msg in results:
                status = "✓" if success else "✗"
                detail = f" ({msg})" if not success else ""
                if on_log:
                    on_log(f"  {status} {path}{detail}")
            all_results.extend(
                [(str(p), s, m) for p, s, m in results]
            )
            downloaded_count += 1
        else:
            if on_log:
                on_log(f"  ✗ Pominięto (błąd pobierania)")

        if on_progress:
            on_progress(idx / total)

    # Rejestracja w historii
    history = load_history()
    register_lesson(history, url, lesson_number, topic,
                    created_at=getattr(phase1, "lesson_created_at", None))

    if on_log:
        on_log(f"\n✅ GOTOWE — pobrano {downloaded_count}/{total} obrazów.")

    return LessonResult(
        success=downloaded_count > 0,
        lesson_number=lesson_number,
        topic=topic,
        total_images=total,
        downloaded_images=downloaded_count,
        save_results=all_results,
    )
