# Mathloader

Aplikacja na Windows do pobierania obrazów lekcji z dynamicznych stron
z dokumentami — zamiast klikać i zapisywać każdy obraz osobno, wklejasz jeden
link i dostajesz gotowy, ponumerowany folder (w tylu kopiach, ile sobie ustawisz).

Interfejs: PySide6 (Qt 6). Strony renderuje dołączona przeglądarka Chromium
(Playwright) — użytkownik końcowy nie instaluje niczego poza samą aplikacją.

---

## Co potrafi

- **Jeden link → cała lekcja.** Przewija stronę do końca (lazy-loading), zbiera
  wszystkie obrazy i pobiera je w oryginalnej jakości.
- **Podgląd przed zapisem** — przeglądasz obrazy w galerii i dopisujesz temat
  lekcji, zanim cokolwiek trafi na dysk.
- **Dowolna liczba kopii zapisu** (dysk lokalny, pendrive, dysk sieciowy);
  aplikacja na bieżąco sprawdza, czy ścieżki są osiągalne, i ostrzega, gdy nie są.
- **Własne formaty nazw** folderów i plików z podglądem na żywo
  (`{nr}`, `{temat}`, `{data}`, `{img}`).
- **Historia pobrań** z automatyczną numeracją lekcji i wykrywaniem duplikatów.
- **Powiadomienie o nowej wersji** — systemowe okno Windows przy starcie,
  gdy na GitHubie pojawi się nowsze wydanie.

---

## Instalacja (dla użytkownika)

Pobierz z zakładki **[Releases](../../releases/latest)**:

| Plik | Dla kogo |
|------|----------|
| `Mathloader-X.Y.Z-Setup.exe` | zwykła instalacja (skrót w Menu Start, dane w `%APPDATA%`) |
| `Mathloader-X.Y.Z-portable.zip` | bez instalacji — rozpakuj i uruchom, dane lądują w podfolderze `data\` |

Przy pierwszym uruchomieniu SmartScreen może pokazać ostrzeżenie
(*„Windows ochronił Twój komputer”*) — instalator nie jest podpisany
certyfikatem. Kliknij **Więcej informacji → Uruchom mimo to**.

---

## Uruchomienie ze źródeł

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python app.py
```

Wymagany Python 3.11+ (testowane na 3.14).

---

## Gdzie aplikacja trzyma dane

Ustala to [paths.py](paths.py) — katalog instalacyjny w `Program Files` jest
tylko do odczytu, więc ustawienia nigdy nie lądują obok pliku `.exe`:

| Tryb | `settings.json`, `lessons_history.json`, log błędów |
|------|------------------------------------------------------|
| deweloperski (`python app.py`) | katalog projektu |
| zainstalowany | `%APPDATA%\Mathloader\` |
| portable (plik `portable.txt` obok exe) | podfolder `data\` |

**Pobrane obrazy lekcji** trafiają wyłącznie tam, gdzie wskażesz w ustawieniach —
deinstalator ich nie rusza.

---

## Struktura projektu

```
app.py                punkt wejścia GUI
config.py             ustawienia (settings.json)
paths.py              katalogi danych, bezpieczny zapis JSON
downloader.py         Playwright, pobieranie obrazów, historia
updater.py            sprawdzanie nowych wydań na GitHubie
version.py            numer wersji + adres repozytorium
qtui/                 interfejs (PySide6): okno, zakładki, motyw, animacje
tools/make_icon.py    generuje assets/mathloader.ico
build.ps1             build: exe + portable ZIP + instalator
Mathloader.spec       konfiguracja PyInstallera
installer.iss         skrypt Inno Setup
docs/                 dokumentacja techniczna
```

---

## Dla rozwijających

- **Budowanie instalatora** → [docs/BUILD.md](docs/BUILD.md)
- **Publikacja na GitHubie i wydawanie aktualizacji** → [docs/PUBLIKACJA.md](docs/PUBLIKACJA.md)
- **Podbicie wersji** → jedna linia w [version.py](version.py)

---

## Licencja

MIT — [LICENSE](LICENSE). Autor: Maksymilian Borowski.
