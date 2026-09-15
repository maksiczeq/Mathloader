"""Mathloader — okno główne (Qt)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QPushButton, QSizePolicy, QStackedWidget, QWidget,
)

from config import AppConfig
from version import APP_VERSION
from qtui import anim
from qtui.download_page import DownloadPage
from qtui.history_page import HistoryPage
from qtui.info_page import InfoPage
from qtui.settings_page import SettingsPage
from qtui.theme import C, I, PAD_LG, PAD_MD, PAD_SM, PAD_XL, RADIUS, STYLESHEET
from qtui.updates import UpdateChecker
from qtui.widgets import TabBar, hbox, label, vbox

TAB_DOWNLOAD, TAB_HISTORY, TAB_SETTINGS, TAB_INFO = 0, 1, 2, 3

BASE_W, BASE_H = 980, 820
MIN_W, MIN_H = 900, 640
SCREEN_MARGIN_W, SCREEN_MARGIN_H = 40, 60   # zapas na pasek zadań i ramkę okna
VALIDATE_MS = 3000


class MainWindow(QWidget):
    """Okno z nagłówkiem, banerem ostrzeżeń i zakładkami."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config
        self._warning_on = False
        self._problem: Optional[tuple[list[str], str]] = None

        self.setObjectName("Root")
        self.setWindowTitle("Mathloader")
        self.setStyleSheet(STYLESHEET)
        # Bez maksymalizacji — rozmiar zmienia wyłącznie sama aplikacja
        # (wysoki podgląd / rozwinięta konsola), patrz `_resize_to`.
        #
        # MSWindowsFixedSizeDialogHint zdejmuje z ramki WS_THICKFRAME. Samo
        # setFixedSize() nie wystarcza: Qt pilnuje wtedy rozmiaru dopiero przez
        # WM_GETMINMAXINFO, więc krawędź nadal łapie kursor rozciągania i okno
        # „drga” pod myszą, mimo że rozmiar się nie zmienia.
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )

        self._fixed_w, self._base_h = self._start_size()
        self.resize(self._fixed_w, self._base_h)
        self._lock_size(self._base_h)

        self._build()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._validate_paths)
        self._timer.start(VALIDATE_MS)
        QTimer.singleShot(150, self._validate_paths)

        self._updates = UpdateChecker(self, self._config)
        self.info_page.check_updates_requested.connect(
            lambda: self._updates.check(manual=True))
        self._updates.check_on_start()

    # ────────────────────────────── budowa

    def _build(self) -> None:
        root = vbox(self, m=PAD_XL, s=PAD_MD)
        root.setContentsMargins(PAD_XL, PAD_LG, PAD_XL, PAD_LG)

        # ── Nagłówek ──
        head = QWidget(self)
        hl = hbox(head)
        hl.addWidget(label(f"{I.SPARK}  Mathloader", "AppTitle"))
        hl.addStretch(1)
        hl.addWidget(label(f"v{APP_VERSION}  •  Qt", "AppVersion"))
        root.addWidget(head)

        # ── Baner ostrzeżenia ──
        self.banner = QFrame(self)
        self.banner.setObjectName("Banner")
        bl = vbox(self.banner, m=PAD_MD, s=4)
        row = QWidget(self.banner)
        rl = hbox(row, s=PAD_SM)
        self.banner_kw = label("", "FieldTitle")
        self.banner_kw.setAlignment(Qt.AlignmentFlag.AlignTop)
        rl.addWidget(self.banner_kw)
        self.banner_text = label("", "Hint", wrap=True)
        rl.addWidget(self.banner_text, 1)
        bl.addWidget(row)

        self.banner_link = QPushButton(f"{I.ARROW_R}  Pokaż więcej szczegółów",
                                       self.banner)
        self.banner_link.setObjectName("Link")
        self.banner_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.banner_link.clicked.connect(self._show_path_details)
        bl.addWidget(self.banner_link, 0, Qt.AlignmentFlag.AlignLeft)
        self.banner.hide()
        root.addWidget(self.banner)

        # ── Zakładki ──
        self.tabs = TabBar(
            [f"{I.DOWNLOAD}   Pobierz",
             f"{I.LIST}   Historia",
             f"{I.GEAR}   Ustawienia",
             f"{I.INFO}   Info"],
            self._switch_tab, self)
        root.addWidget(self.tabs)

        # ── Strony ──
        shell = QFrame(self)
        shell.setObjectName("Surface")
        shell.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Expanding)
        sl = vbox(shell, m=PAD_SM)

        self.stack = QStackedWidget(shell)
        self.download_page = DownloadPage(self._config)
        self.download_page.request_height.connect(self._grow_by)
        self.download_page.history_changed.connect(lambda: self.history_page.refresh())

        self.history_page = HistoryPage(self._config)
        self.settings_page = SettingsPage(self._config)
        self.info_page = InfoPage()

        self.stack.addWidget(self.download_page)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.info_page)
        sl.addWidget(self.stack)
        root.addWidget(shell, 1)

    # ────────────────────────────── zakładki

    def _switch_tab(self, idx: int) -> None:
        if self.stack.currentIndex() == idx:
            return
        self.stack.setCurrentIndex(idx)
        page = self.stack.currentWidget()
        anim.fade_in(page, ms=anim.BASE)
        if idx == TAB_HISTORY:
            self.history_page.refresh()

    # ────────────────────────────── rozmiar okna

    def _avail(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _avail_height(self) -> int:
        return self._avail().height()

    def _start_size(self) -> tuple[int, int]:
        """Rozmiar startowy przycięty do ekranu.

        Okno jest nieskalowalne, więc musi zmieścić się w całości również na
        małym laptopie — inaczej użytkownik nie miałby jak go zmniejszyć.
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        width = max(MIN_W, min(BASE_W, avail.width() - SCREEN_MARGIN_W))
        height = max(MIN_H, min(BASE_H, avail.height() - SCREEN_MARGIN_H))
        return width, height

    def _lock_size(self, height: int) -> None:
        """Przykuwa okno do rozmiaru: koniec z ciągnięciem za krawędź.

        setFixedSize zgłasza menedżerowi okien, że okno jest nieskalowalne —
        znikają uchwyty ramki, przyciąganie do krawędzi (Snap) i Win+↑.
        """
        self.setFixedSize(self._fixed_w, height)

    def _grow_by(self, extra: int) -> None:
        """extra>0 → powiększ okno o tyle pikseli; 0 → wróć do bazowej wysokości."""
        target = (self._base_h if extra <= 0
                  else min(self.height() + extra,
                           self._avail_height() - SCREEN_MARGIN_H))
        self._resize_to(target)

    def _resize_to(self, target_h: int) -> None:
        """Programowa zmiana wysokości — jedyna dozwolona droga do resize'u.

        Zamek trzeba zdjąć na czas animacji: przy setFixedSize Qt przycina
        każdą zmianę geometrii, więc animacja stałaby w miejscu. Po dojściu do
        celu okno jest zamykane na nowy rozmiar.
        """
        avail = self._avail()
        target_h = max(MIN_H, min(target_h, avail.height()))
        if abs(target_h - self.height()) < 4:
            return
        # Rosnąc okno nie może zejść pod krawędź ekranu — nieskalowalnego okna
        # użytkownik nie „ściągnie” już z powrotem chwytem za ramkę.
        end_y = self.y()
        if end_y + target_h > avail.bottom():
            end_y = max(avail.top(), avail.bottom() - target_h)

        self.setMinimumHeight(min(self.height(), target_h))
        self.setMaximumHeight(max(self.height(), target_h))
        anim.animate_height(self, target_h, new_y=end_y, ms=anim.SLOW,
                            on_done=lambda: self._lock_size(target_h))

    # ────────────────────────────── walidacja ścieżek

    def _validate_paths(self) -> None:
        ok: list[str] = []
        bad: list[str] = []
        for p in self._config.save_paths:
            try:
                cur = p.resolve()
                while not cur.exists() and cur.parent != cur:
                    cur = cur.parent
                reachable = cur.exists()
            except OSError:
                reachable = False
            (ok if reachable else bad).append(str(p))

        if not bad and ok:
            self._problem = None
            self._hide_banner()
            self.download_page.set_download_enabled(True)
            self.settings_page.form.highlight_paths([], None)
            self.settings_page.form.hide_detail()
        elif not ok:
            self._problem = (bad, C.ERROR)
            self._show_banner(
                C.ERROR, f"{I.STOP}  BŁĄD:",
                "Brak wykrytych ścieżek zapisu. Upewnij się, że zadeklarowany "
                "dysk istnieje i jest widoczny przez system, a następnie "
                "zaktualizuj ścieżkę.",
                C.TEXT_ON_PRIMARY)
            self.download_page.set_download_enabled(False)
            self.settings_page.form.highlight_paths(bad, C.ERROR)
        else:
            self._problem = (bad, C.WARNING)
            self._show_banner(
                C.WARNING, f"{I.WARN}  OSTRZEŻENIE:",
                "Niektóre dodatkowe ścieżki zapisu są nieaktywne lub "
                "niewykrywalne przez system. Nadal możesz bezpiecznie pobierać "
                "lekcje, ale zostaną zapisane bez wszystkich kopii.",
                C.TEXT_ON_WARNING)
            self.download_page.set_download_enabled(True)
            self.settings_page.form.highlight_paths(bad, C.WARNING)

    def _show_banner(self, color: str, keyword: str, text: str,
                     fg: str) -> None:
        first = not self._warning_on
        self.banner_kw.setText(keyword)
        self.banner_kw.setStyleSheet(f"color: {fg}; font-weight: 700;")
        self.banner_text.setText(text)
        self.banner_text.setStyleSheet(f"color: {fg};")
        self.banner_link.setStyleSheet(
            f"color: {fg}; text-decoration: underline; background: transparent;"
            f" border: none; text-align: left;")
        self.banner.setStyleSheet(
            f"#Banner {{ background: {color}; border-radius: {RADIUS}px; }}")

        if not first:
            return
        self._warning_on = True
        # Wysuwa się z góry, po czym „zaświeca" przez ~1 s.
        anim.reveal(self.banner, ms=anim.BASE)
        QTimer.singleShot(
            anim.BASE + 60,
            lambda: anim.glow(self.banner, color, pulses=2, ms=950))

    def _hide_banner(self) -> None:
        if not self._warning_on:
            return
        self._warning_on = False
        anim.slide_up(self.banner, ms=anim.FAST)

    def _show_path_details(self) -> None:
        self.tabs.set_index(TAB_SETTINGS)
        if not self._problem:
            return
        bad, color = self._problem
        self.settings_page.form.show_detail(color)
        QTimer.singleShot(220, lambda: self.settings_page.form.flash_paths(bad, color))

    # ────────────────────────────── zdarzenia

    def showEvent(self, e) -> None:       # noqa: N802
        super().showEvent(e)
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            anim.fade_in_window(self, ms=280)
