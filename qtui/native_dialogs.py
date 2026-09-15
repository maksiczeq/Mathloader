"""
Mathloader — natywne okna systemowe Windows (Win32 TaskDialog).

Komunikat o nowej wersji ma wyglądać jak komunikat Windows, a nie jak ciemny
motyw aplikacji, dlatego zamiast `QMessageBox` wołamy bezpośrednio
`TaskDialogIndirect` z comctl32 — to samo okno, którego używa system
(nagłówek, ikona, przyciski-polecenia, rozwijane szczegóły).

Degradacja, gdyby się nie udało:
  1. `TaskDialogIndirect`  — comctl32 w wersji 6 (Windows Vista+ z manifestem)
  2. `MessageBoxW`         — zawsze dostępne na Windows
  3. `None`                — nie-Windows; wołający pokazuje wtedy okno Qt

Struktury Win32 są tu pakowane bajt w bajt (`_pack_ = 1`), bo commctrl.h
deklaruje TASKDIALOGCONFIG wewnątrz `#pragma pack(1)`. Domyślne wyrównanie
ctypes dałoby przesunięte pola i błąd E_INVALIDARG.
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

IS_WINDOWS = sys.platform == "win32"

# ── Ikony (MAKEINTRESOURCEW(-1..-4)) ─────────────────────────────────────────
ICON_WARNING = 0xFFFF
ICON_ERROR = 0xFFFE
ICON_INFO = 0xFFFD
ICON_SHIELD = 0xFFFC

# ── Flagi TASKDIALOGCONFIG.dwFlags ───────────────────────────────────────────
TDF_ALLOW_DIALOG_CANCELLATION = 0x0008
TDF_USE_COMMAND_LINKS = 0x0010
TDF_EXPAND_FOOTER_AREA = 0x0040
TDF_POSITION_RELATIVE_TO_WINDOW = 0x1000
TDF_SIZE_TO_CONTENT = 0x0100_0000

# ── Przyciski systemowe / identyfikatory ─────────────────────────────────────
TDCBF_OK = 0x0001
TDCBF_CANCEL = 0x0008
TDCBF_CLOSE = 0x0020

ID_OK = 1
ID_CANCEL = 2
ID_CLOSE = 8

# ── Powiadomienia i komunikaty okna ──────────────────────────────────────────
TDN_CREATED = 0
TDM_CLICK_BUTTON = 0x0400 + 102          # WM_USER + 102

# ── MessageBoxW ──────────────────────────────────────────────────────────────
MB_OK = 0x0000
MB_YESNO = 0x0004
MB_ICONERROR = 0x0010
MB_ICONQUESTION = 0x0020
MB_ICONWARNING = 0x0030
MB_ICONINFORMATION = 0x0040
MB_SETFOREGROUND = 0x0001_0000
ID_YES = 6
ID_NO = 7


@dataclass(frozen=True)
class Button:
    """Przycisk-polecenie. W `text` „\\n” oddziela tytuł od opisu pod spodem."""

    id: int
    text: str


if IS_WINDOWS:
    from ctypes import wintypes

    _LONG_PTR = ctypes.c_ssize_t

    class _TASKDIALOG_BUTTON(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("nButtonID", ctypes.c_int),
            ("pszButtonText", ctypes.c_wchar_p),
        ]

    _CALLBACK = ctypes.WINFUNCTYPE(
        ctypes.c_long,                  # HRESULT
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        _LONG_PTR,
    )

    class _TASKDIALOGCONFIG(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("hwndParent", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("dwFlags", ctypes.c_uint),
            ("dwCommonButtons", ctypes.c_uint),
            ("pszWindowTitle", ctypes.c_wchar_p),
            ("pszMainIcon", ctypes.c_void_p),        # unia HICON / PCWSTR
            ("pszMainInstruction", ctypes.c_wchar_p),
            ("pszContent", ctypes.c_wchar_p),
            ("cButtons", ctypes.c_uint),
            ("pButtons", ctypes.POINTER(_TASKDIALOG_BUTTON)),
            ("nDefaultButton", ctypes.c_int),
            ("cRadioButtons", ctypes.c_uint),
            ("pRadioButtons", ctypes.POINTER(_TASKDIALOG_BUTTON)),
            ("nDefaultRadioButton", ctypes.c_int),
            ("pszVerificationText", ctypes.c_wchar_p),
            ("pszExpandedInformation", ctypes.c_wchar_p),
            ("pszExpandedControlText", ctypes.c_wchar_p),
            ("pszCollapsedControlText", ctypes.c_wchar_p),
            ("pszFooterIcon", ctypes.c_void_p),      # unia HICON / PCWSTR
            ("pszFooter", ctypes.c_wchar_p),
            ("pfCallback", _CALLBACK),
            ("lpCallbackData", _LONG_PTR),
            ("cxWidth", ctypes.c_uint),
        ]

    def _load_task_dialog():
        """comctl32 w wersji 5 nie eksportuje TaskDialogIndirect — wtedy None."""
        try:
            fn = ctypes.WinDLL("comctl32").TaskDialogIndirect
        except (OSError, AttributeError):
            return None
        fn.argtypes = [
            ctypes.POINTER(_TASKDIALOGCONFIG),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(wintypes.BOOL),
        ]
        fn.restype = ctypes.c_long
        return fn

    _TASK_DIALOG = _load_task_dialog()
    _USER32 = ctypes.WinDLL("user32")
else:                                                # pragma: no cover
    _TASK_DIALOG = None
    _USER32 = None


def available() -> bool:
    """True, gdy da się pokazać jakiekolwiek okno systemowe."""
    return IS_WINDOWS


def task_dialog(
    *,
    title: str,
    heading: str,
    content: str,
    buttons: Sequence[Button] = (),
    common_buttons: int = 0,
    expanded: str = "",
    expanded_label: str = "Szczegóły",
    footer: str = "",
    icon: int = ICON_INFO,
    parent_hwnd: int = 0,
    default_id: int = 0,
    on_created: Optional[Callable[[int], None]] = None,
) -> Optional[int]:
    """Pokazuje okno systemowe i zwraca id klikniętego przycisku.

    None oznacza „nie da się” (nie-Windows albo brak comctl32 v6) — wołający
    powinien wtedy sięgnąć po `message_box` lub okno Qt.
    """
    if not IS_WINDOWS or _TASK_DIALOG is None:
        return None

    array = (_TASKDIALOG_BUTTON * len(buttons))()
    for i, btn in enumerate(buttons):
        array[i].nButtonID = btn.id
        array[i].pszButtonText = btn.text

    flags = (TDF_ALLOW_DIALOG_CANCELLATION
             | TDF_POSITION_RELATIVE_TO_WINDOW
             | TDF_SIZE_TO_CONTENT)
    if buttons:
        flags |= TDF_USE_COMMAND_LINKS

    def _handler(hwnd, msg, _wparam, _lparam, _data) -> int:
        if msg == TDN_CREATED and on_created is not None:
            on_created(int(hwnd))
        return 0

    callback = _CALLBACK(_handler)

    cfg = _TASKDIALOGCONFIG()
    cfg.cbSize = ctypes.sizeof(_TASKDIALOGCONFIG)
    cfg.hwndParent = parent_hwnd or None
    cfg.dwFlags = flags
    cfg.dwCommonButtons = common_buttons if (common_buttons or buttons) else TDCBF_OK
    cfg.pszWindowTitle = title
    cfg.pszMainIcon = ctypes.c_void_p(icon)
    cfg.pszMainInstruction = heading
    cfg.pszContent = content
    cfg.cButtons = len(buttons)
    cfg.pButtons = array if buttons else None
    cfg.nDefaultButton = default_id
    cfg.pszExpandedInformation = expanded or None
    cfg.pszExpandedControlText = expanded_label if expanded else None
    cfg.pszCollapsedControlText = expanded_label if expanded else None
    cfg.pszFooter = footer or None
    cfg.pfCallback = callback

    pressed = ctypes.c_int(0)
    radio = ctypes.c_int(0)
    checked = wintypes.BOOL(0)
    try:
        hr = _TASK_DIALOG(ctypes.byref(cfg), ctypes.byref(pressed),
                          ctypes.byref(radio), ctypes.byref(checked))
    except OSError:
        return None
    if hr != 0:                       # S_OK == 0
        return None
    return int(pressed.value)


def click_button(hwnd: int, button_id: int) -> None:
    """Klika przycisk otwartego okna (używane w teście dymnym)."""
    if _USER32 is not None:
        _USER32.SendMessageW(ctypes.c_void_p(hwnd), TDM_CLICK_BUTTON,
                             button_id, 0)


def message_box(*, title: str, text: str, flags: int = MB_OK | MB_ICONINFORMATION,
                parent_hwnd: int = 0) -> Optional[int]:
    """Awaryjne okno systemowe — zwykły MessageBox."""
    if not IS_WINDOWS or _USER32 is None:
        return None
    return int(_USER32.MessageBoxW(ctypes.c_void_p(parent_hwnd or 0), text,
                                   title, flags | MB_SETFOREGROUND))
