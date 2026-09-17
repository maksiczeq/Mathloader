# Budowanie instalatora Mathloader

Instrukcja tworzenia uniwersalnego instalatora dla Windows (64-bit).

---

## 1. Przygotowanie (jednorazowo)

### 1.1 Zależności Pythona

```powershell
.\.venv\Scripts\pip install -r requirements.txt -r requirements-build.txt
.\.venv\Scripts\python -m playwright install chromium
```

> `requirements-build.txt` dokłada tylko PyInstallera. Wersja **≥ 6.16** jest
> wymagana — wcześniejsze nie obsługują Pythona 3.14.

### 1.2 Inno Setup 6

Pobierz i zainstaluj: **https://jrsoftware.org/isdl.php** (darmowe, ~5 MB).
Instaluj w domyślnej lokalizacji — `build.ps1` sam znajdzie `ISCC.exe`.

Bez tego zbudujesz exe i wersję portable, ale nie instalator.

---

## 2. Budowanie

```powershell
.\build.ps1
```

Tyle. Skrypt po kolei:

| Krok | Co robi |
|------|---------|
| 1/6 | Sprawdza venv, PyInstallera i obecność Chromium |
| 2/6 | Generuje ikonę `assets\mathloader.ico` |
| 3/6 | Uruchamia PyInstallera wg `Mathloader.spec` |
| 4/6 | **Weryfikuje paczkę** — exe, ikona, sterownik Playwright, `chrome-headless-shell.exe` |
| 5/6 | Tworzy ZIP portable (z plikiem `portable.txt`) |
| 6/6 | Buduje instalator przez Inno Setup |

Czas: ~3–8 minut. Przydatne przełączniki:

```powershell
.\build.ps1 -SkipInstaller   # bez Inno Setup
.\build.ps1 -Clean           # usuwa build\, dist\, dist_installer\
```

### Co powstaje

```
dist\Mathloader\                              ← gotowa aplikacja, 503 MB
dist_installer\
  ├─ Mathloader-3.0.0-Setup.exe               ← instalator, ~200 MB
  └─ Mathloader-3.0.0-portable.zip            ← wersja bez instalacji, 204 MB
```

> Rozmiary zmierzone na realnym buildzie (PyInstaller 6.22.2, Python 3.14.4).

---

## 3. Gdzie aplikacja trzyma dane

Zależy od trybu — obsługuje to [paths.py](../paths.py):

| Tryb | Kiedy | `settings.json`, `lessons_history.json`, log błędów |
|------|-------|------------------------------------------------------|
| **deweloperski** | `python app.py` | katalog projektu (bez zmian) |
| **zainstalowany** | z instalatora | `%APPDATA%\Mathloader\` |
| **portable** | ZIP + plik `portable.txt` obok exe | podfolder `data\` obok exe |

**To był krytyczny bug**: wcześniej dane zapisywały się obok pliku `.exe`.
W `C:\Program Files\` folder jest tylko do odczytu, więc każdy zapis ustawień
kończyłby się crashem. Pobrane **obrazy lekcji** trafiają tam, gdzie wskażesz
w ustawieniach — instalator i deinstalator nigdy ich nie ruszają.

Użytkownik nie musi tego szukać: *Ustawienia → Opcje zaawansowane → Twoje pliki
z danymi* pokazuje obie ścieżki i otwiera Eksplorator z zaznaczonym plikiem.

### Co gwarantuje, że dane przeżyją aktualizację

| Ryzyko | Zabezpieczenie |
|--------|----------------|
| Instalator nadpisuje pliki programu | Pisze wyłącznie do `{app}`; `%APPDATA%\Mathloader` nie jest w ogóle dotykany |
| Ktoś odinstaluje starą wersję przed instalacją nowej | Pytanie o skasowanie danych ma domyślnie **Nie** i wprost odradza usuwanie przed aktualizacją |
| Wersja portable — podmiana folderu | `portable.txt` instruuje, żeby przenieść podfolder `data\` do nowej paczki |
| Crash / zanik prądu w trakcie zapisu | `write_json_atomic()` w [paths.py](../paths.py): zapis obok + `os.replace()`, więc poprzednia wersja pliku zostaje nietknięta |
| Plik mimo wszystko nieczytelny | `quarantine_broken()` odkłada go jako `*.uszkodzony-RRRRMMDD-GGMMSS.json` zamiast pozwolić nadpisać pustym |

---

## 4. Test przed publikacją

Zrób to **na czystym koncie albo innym komputerze**, nie tam gdzie masz venv —
inaczej nie wykryjesz brakujących zależności.

- [ ] Instalator przechodzi bez błędu (wybierz „tylko dla mnie" — bez UAC)
- [ ] Skrót w Menu Start działa, ikona jest niebieska (nie Pythona)
- [ ] Pierwsze uruchomienie → **kreator konfiguracji**, ustaw folder zapisu
- [ ] Zamknij i uruchom ponownie → kreator **się nie pokazuje** (to test zapisu do `%APPDATA%`)
- [ ] Wklej prawdziwy link lekcji → pobiera obrazy do końca *(najważniejszy test — sprawdza dołączone Chromium)*
- [ ] Zakładka Historia pokazuje pobraną lekcję
- [ ] Historia: „Otwórz” trafia do folderu w **domyślnej** (pierwszej) ścieżce,
      a po odłączeniu tego nośnika — do kolejnej istniejącej kopii
- [ ] Ustawienia: pinezka ustawia ścieżkę domyślną (wiersz idzie na górę),
      a domyślnej nie da się usunąć — „✕” przy niej jest wyszarzone
- [ ] Historia: przełącznik „Ukryj wygasłe” chowa lekcje starsze niż tydzień
- [ ] Zakładka Info pokazuje licencję MIT, autora i **aktualny numer wersji**
- [ ] Info → *Sprawdź aktualizacje* odpowiada oknem systemowym (a nie ciszą)
- [ ] Okna **nie da się rozciągnąć** myszką ani przyciągnąć do krawędzi (Win+↑),
      ale samo rośnie przy wysokim podglądzie i wraca po zamknięciu
- [ ] Deinstalacja pyta o usunięcie ustawień; obrazy lekcji zostają na dysku
- [ ] ZIP portable: rozpakuj, uruchom — dane lądują w podfolderze `data\`

---

## 5. Typowe problemy

**`Executable doesn't exist at ...chrome-headless-shell.exe`**
Chromium nie trafił do paczki. Sprawdź, czy istnieje
`dist\Mathloader\_internal\ms-playwright\`. Jeśli nie —
`python -m playwright install chromium` i zbuduj ponownie.
(Krok 4/6 w `build.ps1` łapie to zanim wypuścisz instalator.)

**Aplikacja startuje i natychmiast znika**
Zajrzyj do `%APPDATA%\Mathloader\mathloader-error.log` — globalny handler
wyjątków w [app.py](../app.py) zapisuje tam pełny ślad stosu i pokazuje okienko
z błędem. Bez tego aplikacja okienkowa ginie bez śladu.

**Windows SmartScreen: „Windows ochronił Twój komputer"**
Normalne dla niepodpisanego instalatora. Użytkownik klika *Więcej informacji →
Uruchom mimo to*. Żeby to usunąć na stałe, potrzebny jest certyfikat Code
Signing (~300–1500 zł/rok, np. Certum Open Source ma tańszą opcję dla projektów
otwartych). Ostrzeżenie znika też samo po kilkuset pobraniach (reputacja).

**Antywirus flaguje plik**
Częste przy PyInstallerze. Dlatego w `.spec` jest `upx=False` — kompresja UPX
drastycznie zwiększa liczbę fałszywych alarmów. Jeśli nadal występuje, zgłoś
fałszywy alarm producentowi antywirusa.

**Paczka `dist\Mathloader` waży znacznie ponad 503 MB**
Sprawdź, czy do `_internal\ms-playwright` nie trafił pełny `chromium-*` (427 MB)
obok `chromium_headless_shell-*` (284 MB). `Mathloader.spec` pakuje tylko ten
drugi — `chromium.launch(headless=True)` innego nie używa.

**`build.ps1` sypie błędami składni z polskimi znakami**
Plik `.ps1` stracił BOM. Windows PowerShell 5.1 czyta skrypty bez BOM-u jako
ANSI (cp1250) i rozwala parser. Zapisz ponownie jako **UTF-8 z BOM** — dotyczy
to też `installer.iss` (Inno Setup zachowuje się tak samo).

---

## 6. Ręcznie, krok po kroku

Gdyby `build.ps1` zawiódł:

```powershell
.\.venv\Scripts\python tools\make_icon.py
.\.venv\Scripts\python -m PyInstaller Mathloader.spec --noconfirm --clean
.\dist\Mathloader\Mathloader.exe          # test przed pakowaniem
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer.iss
```

---

## 7. Podbicie wersji

Wersja jest **w jednym miejscu** — `APP_VERSION` w [version.py](../version.py):

```python
APP_VERSION = "3.1.0"
```

Wszystko inne czyta stamtąd:

| Kto | Skąd bierze |
|-----|-------------|
| nagłówek okna, zakładka Info | `import version` |
| sprawdzanie aktualizacji | porównanie z tagiem wydania na GitHubie |
| [build.ps1](../build.ps1) | regex po `APP_VERSION` (nazwy plików wyjściowych) |
| [installer.iss](../installer.iss) | parametr `/DAppVersion=…` podany przez `build.ps1` |

> Uruchamiając `ISCC.exe installer.iss` ręcznie, z pominięciem `build.ps1`,
> dodaj `/DAppVersion=3.1.0` — inaczej instalator użyje wartości awaryjnej
> wpisanej w `.iss`.

---

## 8. Publikacja i aktualizacje

Wrzucenie projektu na GitHuba oraz wydawanie kolejnych wersji (z okienkiem
„Dostępna nowa wersja aplikacji” u użytkownika) opisuje osobny dokument:
**[PUBLIKACJA.md](PUBLIKACJA.md)**.
