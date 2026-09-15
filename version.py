"""
Mathloader — jedno źródło prawdy o wersji i adresie repozytorium.

Z tego pliku czytają:
  • aplikacja       — nagłówek okna, zakładka Info, sprawdzanie aktualizacji
  • build.ps1       — numer w nazwach `Mathloader-X.Y.Z-Setup.exe` / `-portable.zip`
  • installer.iss   — przez `/DAppVersion=...` przekazane z build.ps1

Podbijając wersję zmieniasz WYŁĄCZNIE `APP_VERSION` tutaj — reszta idzie za tym.
"""
from __future__ import annotations

APP_NAME = "Mathloader"
APP_VERSION = "3.0.0"

# ─────────────────────────────────────────────────────────────────────────────
#  Repozytorium GitHub, z którego aplikacja czyta informacje o nowych wersjach.
#
#  ZMIEŃ `GITHUB_OWNER` na swój login GitHub (oraz `GITHUB_REPO`, jeśli nazwiesz
#  repozytorium inaczej niż „Mathloader”). Dopóki zostaje tu placeholder,
#  sprawdzanie aktualizacji jest wyłączone — aplikacja nie odpytuje cudzego repo
#  i nie pokazuje użytkownikowi błędów sieci.
# ─────────────────────────────────────────────────────────────────────────────
GITHUB_OWNER = "maksiczeq"
GITHUB_REPO = "Mathloader"

_OWNER_PLACEHOLDER = "TWOJ-LOGIN-GITHUB"


def is_repo_configured() -> bool:
    """False, dopóki w `GITHUB_OWNER` siedzi placeholder."""
    return bool(GITHUB_OWNER) and GITHUB_OWNER != _OWNER_PLACEHOLDER


def latest_release_api() -> str:
    """Endpoint z najnowszym wydaniem (pomija szkice i wydania wstępne)."""
    return (f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
            f"/releases/latest")


def releases_page() -> str:
    """Strona wydania — otwierana w przeglądarce, gdy brak pliku do pobrania."""
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
