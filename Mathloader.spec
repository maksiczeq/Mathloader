# -*- mode: python ; coding: utf-8 -*-
"""
Mathloader — konfiguracja builda PyInstaller.

Buduje w trybie ONEDIR (folder, nie jeden plik) i to jest celowe:
do paczki trafia ~271 MB przeglądarki Chromium, a onefile rozpakowywałby
to do katalogu tymczasowego przy KAŻDYM uruchomieniu (kilkanaście sekund
czekania i zapychanie dysku).

Uruchom:  pyinstaller Mathloader.spec --noconfirm --clean
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()          # noqa: F821 — wstrzykiwane przez PyInstaller

# ── Zasoby aplikacji ────────────────────────────────────────────────────────
datas = [
    (str(ROOT / "assets" / "mathloader.ico"), "assets"),
    (str(ROOT / "LICENSE"), "."),
]
binaries = []
hiddenimports = []

# Playwright: pakiet Pythona + sterownik Node (driver/) — bez tego brak API.
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")
datas += pw_datas
binaries += pw_binaries
hiddenimports += pw_hidden


# ── Przeglądarka Chromium ───────────────────────────────────────────────────
def _browser_datas() -> list[tuple[str, str]]:
    """Dołącza headless shell + winldd z %LOCALAPPDATA%\\ms-playwright.

    Świadomie NIE pakujemy pełnego `chromium-*` (427 MB) — chromium.launch(
    headless=True) używa wyłącznie `chromium_headless_shell` (271 MB).
    """
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    found: list[tuple[str, str]] = []
    if not base.is_dir():
        raise SystemExit(
            "BŁĄD: nie znaleziono %LOCALAPPDATA%\\ms-playwright.\n"
            "Uruchom najpierw:  python -m playwright install chromium")
    for pattern in ("chromium_headless_shell-*", "winldd-*"):
        for folder in sorted(base.glob(pattern)):
            found.append((str(folder), f"ms-playwright/{folder.name}"))
    if not any("chromium_headless_shell" in dst for _, dst in found):
        raise SystemExit(
            "BŁĄD: brak chromium_headless_shell w %LOCALAPPDATA%\\ms-playwright.\n"
            "Uruchom:  python -m playwright install chromium")
    return found


datas += _browser_datas()

# ── Moduły do wycięcia (rozmiar!) ───────────────────────────────────────────
excludes = [
    # nieużywane w aplikacji, a ciągnięte przez środowisko
    "tkinter", "unittest", "pydoc", "doctest", "pdb",
    "numpy", "scipy", "skimage", "matplotlib", "pandas",
    "pytesseract", "IPython", "pytest", "setuptools", "pip",
    # ciężkie moduły Qt, których nie dotykamy (QtWebEngine to setki MB)
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtHelp",
    "PySide6.QtDesigner", "PySide6.QtUiTools",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSerialPort", "PySide6.QtSensors",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtNetworkAuth", "PySide6.QtHttpServer", "PySide6.QtWebSockets",
]

a = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mathloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX psuje podpisy i bywa flagowany przez antywirusy
    console=False,             # aplikacja okienkowa — bez czarnej konsoli
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "mathloader.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Mathloader",
)
