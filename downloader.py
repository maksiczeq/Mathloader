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

# Strona lekcji podaje czas w strefie serwera (UTC) — latem w Polsce o 2 h
# wstecz względem zegara użytkownika, zimą o godzinę. Stałe „+2" myliłoby się
# o godzinę przez pół roku, więc bierzemy realne przesunięcie strefy lokalnej.
LINK_EXPIRY_DAYS = 7          # po tygodniu od utworzenia link przestaje działać
SCROLL_MAX_SECONDS = 180      # górny limit przewijania jednej strony

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
    # Dopisywanie tablic do lekcji pobranej wcześniej: numer lekcji i licznik
    # historii zostają nietknięte, a obrazy dostają dalsze numery w jej folderze.
    appended: bool = False
    first_index: int = 1


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


def _entry_summary(entry: dict, history: dict, *, appended: bool = False) -> dict:
    """Skrót wpisu historii — to, co GUI pokazuje w ostrzeżeniu o duplikacie."""
    return {
        "number": entry.get("number", history.get("next_number", 2) - 1),
        "topic": entry.get("topic", ""),
        "downloaded_at": entry.get("downloaded_at", ""),
        "created_at": entry.get("created_at", entry.get("downloaded_at", "")),
        # True, gdy URL trafił tu jako dopisana tablica, a nie jako sama lekcja.
        "appended": appended,
    }


def find_existing_lesson(history: dict, url: str) -> Optional[dict]:
    """Szuka lekcji w historii po URL-u (także wśród dopisanych tablic)."""
    for entry in history.get("lessons", []):
        if entry.get("url") == url:
            return _entry_summary(entry, history)
    # Link dopisanych tablic też był już pobrany — inaczej aplikacja
    # zaproponowałaby założenie z niego nowej lekcji bez słowa ostrzeżenia.
    for entry in history.get("lessons", []):
        for extra in entry.get("appends", []):
            if extra.get("url") == url:
                return _entry_summary(entry, history, appended=True)
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
                    created_at: Optional[str] = None,
                    folders: Optional[list[str]] = None) -> None:
    """Rejestruje pobraną lekcję: aktualizuje licznik i dopisuje wpis do historii.

    `created_at` — realna data utworzenia lekcji (ze strony); od niej liczone
    jest wygaśnięcie linku. Gdy jej brak, używamy chwili pobrania.

    `folders` — ścieżki folderów, które naprawdę powstały. Bez nich historia
    musiałaby zgadywać nazwę z aktualnego szablonu i po jego zmianie (albo przy
    kopii „[2]") przycisk „Otwórz" trafiałby w nieistniejący folder.
    """
    downloaded_at = time.strftime(_HISTORY_TS_FMT)
    created_at = created_at or downloaded_at

    lessons = history.setdefault("lessons", [])
    existing_entry = next((e for e in lessons if e.get("url") == url), None)

    if existing_entry is None:
        entry = {
            "number": lesson_number,
            "url": url,
            "topic": topic,
            "downloaded_at": downloaded_at,
            "created_at": created_at,
        }
        if folders:
            entry["folders"] = list(folders)
        lessons.append(entry)
        # Licznik przesuwamy tylko dla naprawdę nowej lekcji.
        history["next_number"] = max(history.get("next_number", 1), lesson_number + 1)
    else:
        existing_entry["number"] = lesson_number
        existing_entry["topic"] = topic
        existing_entry["downloaded_at"] = downloaded_at
        existing_entry["created_at"] = created_at
        if folders:
            existing_entry["folders"] = list(folders)

    history["last_url"] = url
    history["last_topic"] = topic
    history["last_downloaded_at"] = downloaded_at
    save_history(history)


def lesson_folders(lesson: dict, config) -> list[Path]:
    """Foldery, w których leży ta lekcja.

    Pobieranie zapisuje realne ścieżki w historii (`folders`). Starsze wpisy
    ich nie mają — dla nich nazwę trzeba odtworzyć z aktualnego szablonu, co
    się rozjedzie, jeśli użytkownik zmienił format nazw po pobraniu.
    """
    stored = [Path(f) for f in lesson.get("folders", []) if f]
    if stored:
        return stored
    name = config.format_folder_name(lesson.get("number", 1),
                                     lesson.get("topic", ""))
    return [base / name for base in config.save_paths]


def find_lesson_entry(history: dict, lesson: dict) -> Optional[dict]:
    """Zwraca ŻYWY wpis z historii odpowiadający lekcji (nie kopię).

    Karty w GUI trzymają wczytane wcześniej słowniki; żeby dopisać do nich
    cokolwiek trwale, trzeba odnaleźć ten sam wpis w świeżo wczytanej historii.
    """
    lessons = history.get("lessons", [])
    for entry in lessons:
        if (entry.get("url") == lesson.get("url")
                and entry.get("number") == lesson.get("number")
                and entry.get("downloaded_at") == lesson.get("downloaded_at")):
            return entry
    for entry in lessons:
        if entry.get("url") == lesson.get("url"):
            return entry
    for entry in lessons:
        if entry.get("number") == lesson.get("number"):
            return entry
    return None


def appended_count(lesson: dict) -> int:
    """Ile tablic dopisano do tej lekcji już po jej pobraniu."""
    return sum(int(a.get("images", 0) or 0) for a in lesson.get("appends", []))


def register_append(history: dict, lesson: dict, url: str, images: int,
                    folders: list[str]) -> bool:
    """Dopisuje do historii informację o tablicach doklejonych do lekcji.

    Nowego wpisu NIE tworzy i licznika `next_number` NIE rusza — dlatego
    dopisanie tablic nie zabiera numeru następnej lekcji. False oznacza, że
    wpisu już nie ma (np. skasowany w innej zakładce w trakcie pobierania).
    """
    entry = find_lesson_entry(history, lesson)
    if entry is None:
        return False
    entry.setdefault("appends", []).append({
        "url": url,
        "at": time.strftime(_HISTORY_TS_FMT),
        "images": images,
    })
    # Stare wpisy nie mają listy folderów — skoro właśnie do nich pisaliśmy,
    # zapamiętaj je, żeby „Otwórz" w historii przestało zgadywać z szablonu.
    if not entry.get("folders") and folders:
        entry["folders"] = list(folders)
    save_history(history)
    return True


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
    # Strona doklejająca treść bez końca (albo przeliczająca wysokość w kółko)
    # utrzymywałaby `stale_count` na zerze i pętla nie skończyłaby się nigdy —
    # aplikacja wyglądałaby na zawieszoną. Stąd twardy limit czasu.
    deadline = time.monotonic() + SCROLL_MAX_SECONDS

    while stale_count < 5:
        if time.monotonic() > deadline:
            if on_log:
                on_log(f"Przerywam przewijanie po {SCROLL_MAX_SECONDS} s "
                       f"— strona rośnie bez końca.")
            break
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


def _local_utc_offset() -> timedelta:
    """Przesunięcie strefy lokalnej względem UTC (z poprawką na czas letni)."""
    return datetime.now().astimezone().utcoffset() or timedelta(0)


def extract_lesson_datetime(page) -> Optional[str]:
    """Wyciąga datę+godzinę utworzenia lekcji ze strony i przelicza na czas lokalny.

    Strona zawiera daty w formacie RRRR-MM-DD oraz godziny GG:MM:SS (czas serwera).
    Bierzemy pierwsze pełne wystąpienie i przeliczamy na czas lokalny.
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

    return (dt + _local_utc_offset()).strftime(_HISTORY_TS_FMT)


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
    append_lesson: Optional[dict] = None,
) -> Phase1Result:
    """
    Otwiera stronę, scrolluje, zbiera URL-e obrazów, pobiera
    pierwszy obraz i przepuszcza go przez OCR.

    `append_lesson` — lekcja z historii, do której obrazy mają zostać dopisane.
    Wtedy numer bierzemy z niej, a nie z licznika: dopisywanie tablic nie może
    zająć numeru czekającego na następną lekcję.
    """
    if not is_supported_url(url):
        raise ValueError(
            f"Nieobsługiwany adres. Wymagany format: {SUPPORTED_URL_HINT}"
        )

    history = load_history()
    existing = find_existing_lesson(history, url)
    # Ponowne pobranie tego samego URL-a zachowuje oryginalny numer lekcji
    # (nie tworzy dziury w numeracji ani duplikatu w historii).
    if append_lesson is not None:
        lesson_number = int(append_lesson.get("number", 0) or 0)
    elif existing and existing.get("number"):
        lesson_number = existing["number"]
    else:
        lesson_number = get_next_lesson_number(history)

    if on_log:
        if append_lesson is not None:
            on_log(f"Tryb dopisywania — lekcja #{lesson_number} "
                   f"({append_lesson.get('topic', '') or 'bez tematu'})")
        else:
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

    # Nazwa folderu musi być JEDNA dla wszystkich kopii. Liczona osobno dla
    # każdej ścieżki rozjeżdżała się („1 Lekcja" na dysku, „1 Lekcja [2]" na
    # pendrivie), a historia i tak potrafi otworzyć tylko jedną z nich.
    base_name = config.format_folder_name(lesson_number, topic)
    folder_name = base_name
    copy_num = 2
    while any((p / folder_name).exists() for p in save_paths):
        folder_name = f"{base_name} [{copy_num}]"
        copy_num += 1
    folders = [p / folder_name for p in save_paths]

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
                    created_at=getattr(phase1, "lesson_created_at", None),
                    folders=[str(f) for f in folders])

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


# ──────────────────────────────────────────────
# FAZA 2 (wariant) — dopisanie tablic do lekcji pobranej wcześniej
# ──────────────────────────────────────────────

# Ile kolejnych numerów obrazu sprawdzamy, szukając ostatniego już zapisanego.
# Lekcja to kilkanaście–kilkadziesiąt tablic, więc zapas jest ogromny, a pętla
# działa na gotowej liście nazw z folderu (bez odpytywania dysku co numer).
APPEND_INDEX_LIMIT = 2000


def next_image_index(folders: list[Path], lesson_number: int, topic: str,
                     config) -> int:
    """Pierwszy wolny numer obrazu w folderach lekcji.

    Bierzemy NAJWYŻSZY zajęty numer i dodajemy jeden — nie pierwszą dziurę.
    Gdyby któryś obraz nie pobrał się za pierwszym razem, dopisana tablica
    wskoczyłaby w jego miejsce i zaburzyła kolejność lekcji.
    """
    highest = 0
    for folder in folders:
        try:
            names = {p.name for p in folder.iterdir() if p.is_file()}
        except OSError:
            continue
        for idx in range(1, APPEND_INDEX_LIMIT + 1):
            if config.format_image_name(lesson_number, idx, topic) in names:
                highest = max(highest, idx)
    return highest + 1


def _free_image_index(folders: list[Path], lesson_number: int, topic: str,
                      config, start: int) -> int:
    """Pierwszy numer od `start`, pod którym w żadnym folderze nic nie leży.

    Ostatnia linia obrony przed nadpisaniem: gdy użytkownik zmienił format
    nazw po pobraniu lekcji, `next_image_index` nie rozpozna starych plików
    i wróciłby z jedynką.
    """
    idx = max(1, start)
    while any((folder / config.format_image_name(lesson_number, idx, topic)).exists()
              for folder in folders):
        idx += 1
    return idx


def run_phase2_append(
    url: str,
    lesson: dict,
    phase1: Phase1Result,
    config,
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> LessonResult:
    """Dopisuje obrazy z `url` do folderu lekcji pobranej wcześniej.

    Nowy folder nie powstaje, numer lekcji i licznik historii zostają bez
    zmian — obrazy dostają kolejne numery po tych, które już tam leżą.
    """
    lesson_number = int(lesson.get("number", 0) or 0)
    topic = lesson.get("topic", "") or "Bez_tematu"

    all_folders = lesson_folders(lesson, config)
    folders = [f for f in all_folders if f.exists()]
    if not folders:
        raise FileNotFoundError(
            f"Nie znaleziono folderu lekcji #{lesson_number} "
            f"({all_folders[0] if all_folders else '—'}). "
            f"Sprawdź, czy dysk jest podłączony, a folder nie został przeniesiony."
        )

    missing = [f for f in all_folders if f not in folders]
    if on_log:
        on_log(f"Dopisywanie tablic do lekcji #{lesson_number} ({topic}).")
        for f in folders:
            on_log(f"  → {f}")
        for f in missing:
            on_log(f"  ⚠ pomijam (brak folderu): {f}")

    start = next_image_index(folders, lesson_number, topic, config)
    total = len(phase1.image_urls)
    if on_log:
        on_log(f"Numeracja od {start:02d} (obrazów do dopisania: {total}).")

    downloaded_count = 0
    cursor = start
    all_results: list[tuple[str, bool, str]] = []

    for idx, img_url in enumerate(phase1.image_urls, start=1):
        cursor = _free_image_index(folders, lesson_number, topic, config, cursor)
        filename = config.format_image_name(lesson_number, cursor, topic)
        if on_log:
            on_log(f"[{idx}/{total}] {filename}")

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
            all_results.extend([(str(p), s, m) for p, s, m in results])
            downloaded_count += 1
            cursor += 1
        else:
            if on_log:
                on_log("  ✗ Pominięto (błąd pobierania)")

        if on_progress:
            on_progress(idx / total)

    if downloaded_count:
        history = load_history()
        noted = register_append(history, lesson, url, downloaded_count,
                                [str(f) for f in folders])
        if not noted and on_log:
            # Pliki leżą na dysku, więc to nie jest błąd pobierania — ale bez
            # wpisu historia nie pokaże, skąd te tablice się wzięły.
            on_log("⚠ Lekcji nie ma już w historii — tablice zapisano, "
                   "ale nie odnotowano ich w jej wpisie.")

    if on_log:
        on_log(f"\n✅ GOTOWE — dopisano {downloaded_count}/{total} obrazów "
               f"do lekcji #{lesson_number}.")

    return LessonResult(
        success=downloaded_count > 0,
        lesson_number=lesson_number,
        topic=topic,
        total_images=total,
        downloaded_images=downloaded_count,
        save_results=all_results,
        appended=True,
        first_index=start,
    )
