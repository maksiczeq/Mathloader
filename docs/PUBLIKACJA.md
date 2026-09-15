# Publikacja na GitHubie i wydawanie aktualizacji

Instrukcja krok po kroku: jak wrzucić Mathloadera do repozytorium i jak potem
wypuszczać nowe wersje tak, żeby użytkownikom pokazało się systemowe okno
**„Dostępna nowa wersja aplikacji”**.

Kolejność ma znaczenie — sekcje 1–5 robisz raz, sekcję 6 przy każdej aktualizacji.

> **Otwieraj PowerShell, nie `cmd`.** Wszystkie komendy tutaj są w składni
> PowerShella (Win+X → *Terminal* / *Windows PowerShell*); `build.ps1` i tak
> działa tylko tam.
>
> W `cmd.exe` polecenie `cd D:\Programowanie` **nie zmienia dysku** — prompt
> zostaje na `C:\Users\…`, a git zgłasza wtedy *„fatal: not a git repository"*,
> bo szuka repozytorium w katalogu domowym. Gdybyś już był w `cmd`, użyj
> `cd /d D:\Programowanie` albo wpisz najpierw samo `D:`.

---

## 1. Zainstaluj Gita (jednorazowo)

Na tym komputerze Gita jeszcze nie ma. W PowerShellu:

```powershell
winget install --id Git.Git -e --source winget
```

**Zamknij i otwórz terminal ponownie** (instalator dopisuje Gita do PATH), potem
sprawdź i ustaw się jako autor commitów:

```powershell
git --version
git config --global user.name  "Maksymilian Borowski"
git config --global user.email "maks-24@o2.pl"
```

> **Adres e-mail w commitach jest publiczny.** Jeśli wolisz go nie pokazywać,
> załóż najpierw konto GitHub, wejdź w *Settings → Emails*, zaznacz **Keep my
> email addresses private** i użyj adresu `12345678+login@users.noreply.github.com`,
> który tam znajdziesz, zamiast prywatnego.

---

## 2. Sprawdź repozytorium nadrzędne

Katalog **`D:\Programowanie`** jest osobnym repozytorium gita obejmującym inne
projekty. Na GitHuba ma trafić **sam `lesson-downloader`**, więc najpierw
sprawdź, czy tamto repozytorium go nie śledzi:

```powershell
git -C D:\Programowanie ls-files lesson-downloader
```

**Pusty wynik = nie ma nic do roboty** — tak jest w tym projekcie (śledzony jest
tam tylko `techfix.net.pl`). Przejdź do sekcji 3.

Gdyby jednak coś wypisało, odczep projekt:

```powershell
cd D:\Programowanie
git rm -r --cached lesson-downloader          # przestaje śledzić, plików NIE kasuje
git commit -m "lesson-downloader ma własne repozytorium"
```

Opcjonalnie, żeby `git status` w tamtym repozytorium przestał wypisywać projekt
jako nieśledzony:

```powershell
Add-Content D:\Programowanie\.gitignore "lesson-downloader/"
```

---

## 3. Utwórz repozytorium na GitHubie

1. Wejdź na **https://github.com/new**
2. **Repository name:** `Mathloader`
3. **Public** — repozytorium **musi być publiczne**, żeby sprawdzanie aktualizacji
   działało u użytkowników bez logowania (prywatne API wymaga tokenu).
4. **Nie** zaznaczaj „Add a README”, „Add .gitignore” ani „Choose a license” —
   te pliki już są w projekcie i puste repo uniknie konfliktu przy pierwszym pushu.
5. *Create repository*.

---

## 4. Wskaż aplikacji, gdzie ma szukać aktualizacji

W [version.py](../version.py) jest już wpisane:

```python
GITHUB_OWNER = "maksiczeq"       # z Twojego `git config --global user.email`
GITHUB_REPO  = "Mathloader"      # zmień, jeśli nazwiesz repozytorium inaczej
```

Popraw `GITHUB_OWNER`, jeśli repozytorium ma powstać na innym koncie lub
w organizacji. Wpisanie z powrotem `TWOJ-LOGIN-GITHUB` **wyłącza** sprawdzanie
aktualizacji — aplikacja wtedy w ogóle nie odpytuje sieci.

---

## 5. Pierwszy wrzut kodu

```powershell
cd D:\Programowanie\lesson-downloader
git init -b main
git add -A
git status --short          # ← ZOBACZ, co poleci; patrz uwagi niżej
git commit -m "Mathloader 3.0.0"
git remote add origin https://github.com/twoj-login/Mathloader.git
git push -u origin main
```

Przy pierwszym `push` otworzy się okno logowania do GitHuba (Git Credential
Manager) — zaloguj się w przeglądarce, hasło zapisze się w Menedżerze
poświadczeń Windows i więcej o nie nie zapyta.

**Czego NIE może być na liście z `git status --short`:**

| Nie powinno się pojawić | Dlaczego |
|-------------------------|----------|
| `dist_installer/…exe`, `…zip` | 149 MB i 214 MB — GitHub odrzuca pliki > 100 MB (idą do Release, nie do repo) |
| `dist/`, `build/` | artefakty PyInstallera, ~500 MB |
| `.venv/` | środowisko Pythona, odtwarzalne z `requirements.txt` |
| `settings.json`, `lessons_history.json` | Twoje prywatne ścieżki i historia lekcji |

Wszystko to jest już wpisane w [.gitignore](../.gitignore) — ta tabela jest do
sprawdzenia, czy faktycznie zadziałało. Gdyby coś dużego mimo wszystko weszło do
commita, cofnij go przez `git reset --soft HEAD~1`, popraw `.gitignore` i zrób
commit jeszcze raz (plik > 100 MB, który już poleciał na GitHuba, zostaje w
historii i trzeba ją przepisywać — łatwiej go tam nie wpuścić).

---

## 6. Wydanie nowej wersji (to się powtarza)

Numer wersji ma **jedno źródło prawdy** — `APP_VERSION` w [version.py](../version.py).
Czytają go: nagłówek okna, zakładka Info, `build.ps1` (nazwy plików) oraz
`installer.iss` (przez `/DAppVersion`). Nigdzie indziej go nie zmieniasz.

### 6.1 Podbij numer

```python
# version.py
APP_VERSION = "3.1.0"
```

Zasada (semantic versioning): `3.0.0 → 3.0.1` poprawka błędu,
`3.0.0 → 3.1.0` nowa funkcja, `3.0.0 → 4.0.0` zmiana wywracająca dotychczasowe
działanie.

### 6.2 Zbuduj paczki

```powershell
.\build.ps1
```

Powstaną `dist_installer\Mathloader-3.1.0-Setup.exe` oraz
`Mathloader-3.1.0-portable.zip`. Szczegóły i rozwiązywanie problemów: [BUILD.md](BUILD.md).

### 6.3 Wypchnij kod

```powershell
git add -A
git commit -m "3.1.0: krótki opis zmian"
git push
```

### 6.4 Opublikuj wydanie (Release)

**Przez stronę** (najprościej):

1. Repozytorium → zakładka **Releases** → *Draft a new release*
2. **Choose a tag** → wpisz `v3.1.0` → *Create new tag on publish*
3. **Release title:** `Mathloader 3.1.0`
4. **Opis** — to, co tu wpiszesz, użytkownik zobaczy w okienku aktualizacji po
   rozwinięciu **„Co nowego w tej wersji”**. Pisz punktami, po ludzku:
   ```
   - Okno aplikacji nie daje się już rozciągać myszką
   - Powiadomienie o nowej wersji
   - Poprawka: podgląd nie migał przy zmianie obrazu
   ```
5. **Przeciągnij oba pliki** z `dist_installer\` w pole *Attach binaries*
   (Release przyjmuje pliki do 2 GB — inaczej niż samo repozytorium).
6. Zostaw odznaczone *Set as a pre-release* — aplikacja pyta o **latest release**
   i wydania wstępne celowo pomija.
7. *Publish release*.

**Przez konsolę** (szybsze, jeśli zainstalujesz `winget install GitHub.cli`
i raz wykonasz `gh auth login`):

```powershell
gh release create v3.1.0 `
  dist_installer\Mathloader-3.1.0-Setup.exe `
  dist_installer\Mathloader-3.1.0-portable.zip `
  --title "Mathloader 3.1.0" `
  --notes "- Okno nie daje się rozciągać`n- Powiadomienie o nowej wersji"
```

### 6.5 Sprawdź efekt

Uruchom u siebie **starszą** wersję (np. zainstalowaną z poprzedniego
instalatora) — po ~2 sekundach od startu wyskoczy systemowe okno
„Dostępna nowa wersja aplikacji”.

---

## 7. Zasady, o które łatwo się potknąć

| Zasada | Co się stanie, jeśli ją złamiesz |
|--------|----------------------------------|
| Tag wydania = `APP_VERSION` (z „v” lub bez — obie formy działają) | Wersja 3.1.0 z tagiem `v3.0.9` nie zostanie uznana za nowszą i nikt nie dostanie powiadomienia |
| Repozytorium publiczne | API GitHuba zwróci 404, sprawdzanie aktualizacji milczy |
| Instalator w **Release**, nie w repo | Push z plikiem > 100 MB zostanie odrzucony |
| Nazwa pliku kończy się na `Setup.exe` | Updater wybiera do pobrania: instalator → inny `.exe` → `.zip`; przy braku plików otwiera stronę wydania |
| Nie zaznaczaj *pre-release* dla zwykłych wydań | `releases/latest` je pomija — wydanie będzie niewidoczne dla aplikacji |
| Najpierw `git push`, potem Release | Tag wskaże kod, którego nie ma jeszcze na GitHubie |

---

## 8. Jak działa mechanizm aktualizacji

| Element | Plik |
|---------|------|
| Numer wersji i adres repo | [version.py](../version.py) |
| Zapytanie do GitHuba, porównanie wersji | [updater.py](../updater.py) |
| Okno systemowe (Win32 TaskDialog) | [qtui/native_dialogs.py](../qtui/native_dialogs.py) |
| Połączenie tego w całość | [qtui/updates.py](../qtui/updates.py) |

Przebieg:

1. ~1,8 s po starcie okna leci jedno zapytanie HTTP do
   `api.github.com/repos/<owner>/<repo>/releases/latest` (limit bez logowania:
   60 zapytań na godzinę — jedno uruchomienie = jedno zapytanie).
2. Numer z `tag_name` jest porównywany z `APP_VERSION` liczba po liczbie
   (`3.1` > `3.0.9`).
3. Jeśli wersja jest nowsza, pokazuje się **okno systemowe Windows** (nie ciemny
   dialog aplikacji) z trzema przyciskami:
   - **Pobierz wersję X** — otwiera link do instalatora w przeglądarce,
   - **Przypomnij później** — nic nie zapisuje, wróci przy następnym starcie,
   - **Pomiń tę wersję** — zapisuje `skip_version` w `settings.json`, o tej
     konkretnej wersji więcej nie przypomni (następna i tak się pokaże).
4. Brak sieci, brak wydań albo limit API przy starcie = **cisza**. Użytkownik
   zobaczy powód tylko wtedy, gdy sam kliknie **Sprawdź aktualizacje**
   w zakładce *Info*.

### Testowanie bez wypuszczania wersji

Ustaw tymczasowo w `version.py` `APP_VERSION = "0.0.1"`, uruchom `python app.py`
i kliknij *Info → Sprawdź aktualizacje* — powinno pokazać się okno z najnowszym
wydaniem z GitHuba. Potem przywróć prawdziwy numer.
