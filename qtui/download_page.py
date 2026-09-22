"""
Mathloader — zakładka „Pobierz" (Qt).

Przepływ: URL → skan strony (Phase1, wątek) → podgląd obrazów + temat →
pobieranie (Phase2, wątek) → podsumowanie z listą folderów.
"""
from __future__ import annotations

import io
import os
import subprocess
from typing import Optional

from PySide6.QtCore import QByteArray, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from config import AppConfig
from downloader import (
    SUPPORTED_URL_HINT, LessonResult, Phase1Result, appended_count,
    find_existing_lesson, is_supported_url, lesson_folders, load_history,
    sanitize_filename,
)
from qtui import anim, workers
from qtui.theme import (
    C, G, I, PAD_LG, PAD_MD, PAD_SM, PAD_XL, RADIUS_SM,
)
from qtui.widgets import (
    BaseDialog, Toast, boards_word, card, hbox, label, plural, restyle,
    set_glyph, vbox,
)

PREVIEW_MIN_H = 220
PREVIEW_MAX_H = 820
CONSOLE_COLLAPSED = 58
CONSOLE_EXPANDED = 300
STATUS_AUTOHIDE_MS = 20000

# Napisy przycisków w stanie spoczynku — używane też przy cofaniu pytania
# o duplikat, więc muszą być w jednym miejscu.
DOWNLOAD_TEXT = "  Pobierz"
NO_TOPIC = ("", "Bez_tematu", "*Bez Tematu*", "Bez Tematu")


def lesson_caption(lesson: dict) -> str:
    """Podpis lekcji: „#7 — WIELOMIANY”, z zapasem na lekcje bez tematu."""
    topic = lesson.get("topic", "")
    nice = "bez tematu" if topic in NO_TOPIC else topic
    return f"#{lesson.get('number', '?')} — {nice}"


class LessonPickerDialog(BaseDialog):
    """Wybór lekcji, do której dopisujemy tablice z bieżącego linku."""

    def __init__(self, parent: Optional[QWidget], lessons: list[dict],
                 config: AppConfig):
        super().__init__(parent, "Dopisz do wcześniejszej lekcji", width=560)
        self._lessons = lessons
        self._config = config

        lay = vbox(self, m=PAD_XL, s=PAD_MD)
        lay.addWidget(label("Do której lekcji dopisać tablice?",
                            "DialogTitle", wrap=True))
        lay.addWidget(label(
            "Obrazy z wklejonego linku trafią do folderu wybranej lekcji "
            "i dostaną dalsze numery. Nowa lekcja nie powstanie, a licznik "
            "kolejnych numerów zostanie nietknięty.", "Hint", wrap=True))

        self.combo = QComboBox(self)
        for lesson in lessons:
            date = (lesson.get("created_at")
                    or lesson.get("downloaded_at", ""))[:10]
            added = appended_count(lesson)
            extra = f"   (+{added} {boards_word(added)})" if added else ""
            self.combo.addItem(f"{lesson_caption(lesson)}   •   {date}{extra}")
        self.combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo.currentIndexChanged.connect(self._sync)
        lay.addWidget(self.combo)

        self.folder_label = label("", "Muted", wrap=True)
        lay.addWidget(self.folder_label)
        lay.addSpacing(PAD_SM)

        row = QWidget(self)
        rl = hbox(row, s=PAD_MD)
        self.ok = QPushButton("  Wybierz lekcję", row)
        self.ok.setObjectName("Primary")
        set_glyph(self.ok, "CHECK")
        self.ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok.clicked.connect(self.accept)

        no = QPushButton("Anuluj", row)
        no.setObjectName("CardAction")
        no.setMinimumHeight(38)
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.clicked.connect(self.reject)

        rl.addWidget(self.ok, 1)
        rl.addWidget(no, 1)
        lay.addWidget(row)

        self._sync()

    def selected(self) -> Optional[dict]:
        idx = self.combo.currentIndex()
        return self._lessons[idx] if 0 <= idx < len(self._lessons) else None

    def _sync(self) -> None:
        """Podpowiada folder docelowy — i blokuje wybór, gdy go nie ma.

        Dopisanie do lekcji, której folder zniknął (skasowany albo na
        odłączonym pendrivie), skończyłoby się błędem dopiero po całym
        skanowaniu strony. Lepiej powiedzieć to od razu.
        """
        lesson = self.selected()
        folders = lesson_folders(lesson, self._config) if lesson else []
        existing = [f for f in folders if f.exists()]
        if existing:
            more = len(existing) - 1
            extra = (f"   (+{more} {plural(more, 'kopia', 'kopie', 'kopii')})"
                     if more else "")
            self.folder_label.setText(f"{I.FOLDER}  {existing[0]}{extra}")
            self.folder_label.setObjectName("Muted")
        else:
            self.folder_label.setText(
                f"{I.WARN}  Nie znaleziono folderu tej lekcji. Sprawdź, czy "
                f"dysk jest podłączony, a folder nie został przeniesiony.")
            self.folder_label.setObjectName("Warn")
        self.ok.setEnabled(bool(existing))
        restyle(self.folder_label)


class DownloadPage(QWidget):
    """Główny widok pracy: URL → podgląd → pobieranie."""

    IDLE, LOADING, REVIEW, DOWNLOADING, DONE = range(5)

    APPEND_TEXT = "Dopisz tablice do wcześniejszej lekcji"

    request_height = Signal(int)     # sugerowana wysokość okna
    history_changed = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        self._state = self.IDLE
        self._phase1: Optional[Phase1Result] = None
        self._current_url = ""
        self._download_allowed = True
        # Lekcja z historii, do której dopisujemy tablice (None = nowa lekcja).
        self._append_target: Optional[dict] = None
        # (tryb, URL) czekające na potwierdzenie duplikatu — drugie kliknięcie
        # w TEN SAM przycisk z tym samym adresem oznacza „wiem, pobierz mimo to”.
        self._pending: Optional[tuple[str, str]] = None
        self._preview_bytes: dict[int, bytes] = {}
        self._preview_idx = 0
        self._console_expanded = False
        # Jeden timer na cale zycie strony: kazde pobranie tylko go restartuje.
        # Tworzenie nowego przy kazdym koncu pobierania zostawialo poprzednie
        # (wciaz podpiete do _hide_status) jako dzieci widgetu.
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_status)
        self._job = None            # aktywne zadanie w tle — trzymaj referencję!
        self._img_jobs: dict[int, object] = {}
        self._build()

    # ────────────────────────────── budowa UI

    def _build(self) -> None:
        root = vbox(self, m=PAD_LG, s=PAD_MD)

        # ── Karta URL ──
        url_card = card(self)
        ucl = vbox(url_card, m=PAD_LG, s=PAD_SM)
        ucl.addWidget(label("URL strony z lekcją", "FieldTitle"))

        row = QWidget(url_card)
        rl = hbox(row, s=PAD_SM)
        self.url_edit = QLineEdit(row)
        self.url_edit.setPlaceholderText(
            "http://sw.syrjb.com:8081/view/oss/viewDocument/[...]"
        )
        self.url_edit.textChanged.connect(self._on_url_changed)
        self.url_edit.returnPressed.connect(self._on_download)
        rl.addWidget(self.url_edit, 1)

        self.download_btn = QPushButton("  Pobierz", row)
        self.download_btn.setObjectName("Primary")
        set_glyph(self.download_btn, "DOWNLOAD")
        self.download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_btn.setMinimumWidth(160)
        self.download_btn.clicked.connect(self._on_download)
        rl.addWidget(self.download_btn)
        ucl.addWidget(row)

        # Tryb pracy, nie druga akcja: zaznaczone = „Pobierz” dokłada tablice
        # do wskazanej lekcji, zamiast zakładać nową.
        self.append_check = QCheckBox(self.APPEND_TEXT, url_card)
        self.append_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.append_check.setToolTip(
            "Obrazy z tego linku trafią do folderu lekcji pobranej wcześniej "
            "— bez nowego numeru i bez ręcznego przestawiania licznika.")
        self.append_check.toggled.connect(self._on_append_toggled)
        ucl.addWidget(self.append_check)

        self.append_note = label("", "Accent", wrap=True)
        self.append_note.hide()
        ucl.addWidget(self.append_note)

        self.dup_label = label("", "Warn", wrap=True)
        self.dup_label.hide()
        ucl.addWidget(self.dup_label)

        root.addWidget(url_card)

        # ── Środek: znak wodny + karta statusu + karta podglądu ──
        self.middle = QWidget(self)
        self.middle.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Expanding)
        ml = vbox(self.middle, s=PAD_MD)

        self.watermark = QLabel("Mathloader", self.middle)
        self.watermark.setObjectName("Watermark")
        self.watermark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.watermark.lower()

        self._build_status_card(ml)
        self._build_review_card(ml)
        # Gdy podgląd jest ukryty, wolne miejsce zabiera ten spacer (karta
        # statusu zostaje przy górnej krawędzi); gdy widoczny — dominuje podgląd.
        ml.addStretch(1)
        root.addWidget(self.middle, 1)

        # ── Konsola ──
        self._build_console(root)

        self.status_card.hide()
        self.review_card.hide()

    def _build_status_card(self, parent_layout: QVBoxLayout) -> None:
        self.status_card = card(self.middle)
        # Pasek statusu nie rozciąga się — wolne miejsce zostaje na znak wodny.
        self.status_card.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Maximum)
        lay = vbox(self.status_card, m=PAD_LG, s=PAD_SM)

        top = QWidget(self.status_card)
        tl = hbox(top)
        self.status_title = label("", "FieldTitle")
        self.status_pct = label("", "StatusPct")
        tl.addWidget(self.status_title, 1)
        tl.addWidget(self.status_pct)
        lay.addWidget(top)

        self.progress = QProgressBar(self.status_card)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)

        self.status_sub = label("", "Muted")
        lay.addWidget(self.status_sub)

        self.paths_box = QWidget(self.status_card)
        self.paths_layout = vbox(self.paths_box, s=PAD_SM)
        self.paths_box.hide()
        lay.addWidget(self.paths_box)

        parent_layout.addWidget(self.status_card)

    def _build_review_card(self, parent_layout: QVBoxLayout) -> None:
        self.review_card = card(self.middle)
        self.review_card.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Expanding)
        lay = vbox(self.review_card, m=PAD_LG, s=PAD_MD)
        self.review_title = label("Podgląd obrazów", "FieldTitle")
        lay.addWidget(self.review_title)

        content = QWidget(self.review_card)
        cl = hbox(content, s=PAD_LG)

        # Galeria
        gallery = QWidget(content)
        gl = vbox(gallery, s=PAD_SM)

        self.preview = QLabel(gallery)
        self.preview.setObjectName("PreviewArea")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(PREVIEW_MIN_H)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Expanding)
        gl.addWidget(self.preview, 1)

        nav = QWidget(gallery)
        nl = hbox(nav)
        self.prev_btn = QPushButton(G.CHEVRON_L, nav)
        self.prev_btn.setObjectName("NavArrow")
        self.prev_btn.setFixedWidth(44)
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self._change_preview(-1))

        self.idx_label = label("1 / 1", "Muted")
        self.idx_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.next_btn = QPushButton(G.CHEVRON_R, nav)
        self.next_btn.setObjectName("NavArrow")
        self.next_btn.setFixedWidth(44)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(lambda: self._change_preview(1))

        nl.addWidget(self.prev_btn)
        nl.addWidget(self.idx_label, 1)
        nl.addWidget(self.next_btn)
        gl.addWidget(nav)
        cl.addWidget(gallery, 1)

        # Kolumna tematu
        topic = card(content, surface=True)
        topic.setFixedWidth(248)
        tl = vbox(topic, m=PAD_MD, s=PAD_SM)
        self.topic_title = label(f"{I.TOPIC}  Temat lekcji", "FieldTitle")
        tl.addWidget(self.topic_title)

        self.topic_edit = QLineEdit(topic)
        self.topic_edit.setPlaceholderText("Wpisz temat lekcji…")
        self.topic_edit.returnPressed.connect(self._on_confirm)
        tl.addWidget(self.topic_edit)

        self.topic_hint = label("Możesz wpisać temat lub pozostawić puste.",
                                "Muted", wrap=True)
        tl.addWidget(self.topic_hint)
        tl.addStretch(1)

        self.confirm_btn = QPushButton("  Zatwierdź i pobierz", topic)
        self.confirm_btn.setObjectName("Success")
        set_glyph(self.confirm_btn, "CHECK")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._on_confirm)
        tl.addWidget(self.confirm_btn)

        self.cancel_btn = QPushButton(f"{I.CROSS}   Anuluj", topic)
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        tl.addWidget(self.cancel_btn)

        cl.addWidget(topic)
        lay.addWidget(content, 1)
        parent_layout.addWidget(self.review_card, 100)

    def _build_console(self, root: QVBoxLayout) -> None:
        head = QWidget(self)
        hl = hbox(head)
        hl.addWidget(label(f"{I.CONSOLE}  Konsola", "Hint"))
        hl.addStretch(1)

        self.console_btn = QPushButton(f"{I.CHEVRON_D}  Rozwiń", head)
        self.console_btn.setObjectName("Ghost")
        self.console_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.console_btn.clicked.connect(self._toggle_console)
        hl.addWidget(self.console_btn)
        root.addWidget(head)

        self.console = QPlainTextEdit(self)
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        self.console.setFixedHeight(CONSOLE_COLLAPSED)
        self.console.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.console)

    # ────────────────────────────── znak wodny

    def resizeEvent(self, e) -> None:       # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "watermark"):
            self.watermark.adjustSize()
            w, h = self.middle.width(), self.middle.height()
            self.watermark.move((w - self.watermark.width()) // 2,
                                (h - self.watermark.height()) // 2)
        self._rescale_preview()

    # ────────────────────────────── konsola

    def log(self, message: str) -> None:
        self.console.appendPlainText(message)
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self) -> None:
        self.console.clear()

    def _toggle_console(self) -> None:
        self._console_expanded = not self._console_expanded
        target = CONSOLE_EXPANDED if self._console_expanded else CONSOLE_COLLAPSED
        self.console.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if self._console_expanded
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.console_btn.setText(
            f"{I.CHEVRON_U}  Zwiń" if self._console_expanded
            else f"{I.CHEVRON_D}  Rozwiń"
        )
        a = QPropertyAnimation(self.console, QByteArray(b"maximumHeight"), self)
        a.setDuration(anim.BASE)
        a.setStartValue(self.console.height())
        a.setEndValue(target)
        a.setEasingCurve(anim.EASE_OUT)
        a.finished.connect(lambda: self.console.setFixedHeight(target))
        anim._keep(self.console, a, "_h_anim")
        a.start()
        if not self._console_expanded:
            sb = self.console.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ────────────────────────────── stany

    def is_busy(self) -> bool:
        """True, gdy trwa skanowanie albo pobieranie lekcji.

        Pyta o to aktualizacja: zamyka aplikację, więc nie może wejść w środek
        pobierania — przerwana lekcja zostawiłaby połowę obrazów na dysku.
        """
        return self._state in (self.LOADING, self.DOWNLOADING)

    def set_download_enabled(self, enabled: bool) -> None:
        self._download_allowed = enabled
        if self._state in (self.IDLE, self.DONE):
            self.download_btn.setEnabled(enabled)
            self.append_check.setEnabled(enabled)

    def _set_state(self, state: int) -> None:
        self._state = state
        idle_like = state in (self.IDLE, self.DONE)
        self.url_edit.setEnabled(idle_like)
        self.download_btn.setEnabled(idle_like and self._download_allowed)
        self.append_check.setEnabled(idle_like and self._download_allowed)

        if state == self.IDLE:
            self._set_main_button(DOWNLOAD_TEXT, "DOWNLOAD")
            self._set_append_target(None)
            anim.fade_out(self.status_card, on_done=self.status_card.hide)
            anim.fade_out(self.review_card, on_done=self.review_card.hide)
            self.dup_label.hide()
            self.request_height.emit(0)

        elif state == self.LOADING:
            self._set_main_button("Ładowanie…")
            self.review_card.hide()
            self.status_title.setText(f"{I.SCAN}   Skanowanie strony z lekcją…")
            self.status_pct.setText("")
            self.status_sub.setText(
                "Playwright otwiera przeglądarkę i przewija stronę. "
                "To może chwilę potrwać."
            )
            self.progress.setRange(0, 0)          # tryb nieokreślony
            self.paths_box.hide()
            self.progress.setObjectName("")
            self.progress.setStyleSheet("")
            anim.reveal(self.status_card, ms=anim.BASE)

        elif state == self.REVIEW:
            self._set_main_button(DOWNLOAD_TEXT, "DOWNLOAD")
            self.status_card.hide()
            self._sync_review_mode()
            anim.reveal(self.review_card, ms=anim.BASE)

        elif state == self.DOWNLOADING:
            self._set_main_button("Pobieranie…")
            self.review_card.hide()
            self.progress.setRange(0, 1000)
            self.progress.setValue(0)
            self.status_title.setText(self._busy_title())
            self.status_pct.setText("0%")
            self.status_sub.setText("")
            anim.reveal(self.status_card, ms=anim.BASE)

        elif state == self.DONE:
            self._set_main_button("  Nowe pobieranie", "REFRESH")
            self.request_height.emit(0)

    # ────────────────────────────── Phase 1

    def _on_url_changed(self, text: str) -> None:
        if self._pending and text.strip() != self._pending[1]:
            self._reset_pending()
        elif not self._pending and self.dup_label.isVisible():
            # schowaj komunikat o nieobsługiwanym adresie po edycji
            anim.fade_out(self.dup_label)

    def _set_main_button(self, text: str, glyph: str = "") -> None:
        """Podpis i ikona głównego przycisku zmieniają się razem ze stanem."""
        self.download_btn.setText(text)
        if glyph:
            set_glyph(self.download_btn, glyph)
        else:
            self.download_btn.setIcon(QIcon())

    def _restyle(self, w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)

    def _on_download(self) -> None:
        """Adres → duplikat → skan. Tryb wynika z zaznaczonego pola wyboru."""
        url = self.url_edit.text().strip()
        if not url:
            self.log("Podaj URL strony z lekcją.")
            return

        if not is_supported_url(url):
            self._reset_pending()
            self._show_url_error()
            return

        # Powtórne kliknięcie z tym samym adresem = zgoda na duplikat.
        if self._pending == url:
            self._reset_pending()
            self._start_phase1(url)
            return

        self._current_url = url
        self._clear_log()
        self._reset_pending()
        self.paths_box.hide()

        existing = find_existing_lesson(load_history(), url)
        if existing:
            self._warn_duplicate(url, existing)
            return

        self._start_phase1(url)

    def _show_url_error(self) -> None:
        self.dup_label.setObjectName("Err")
        self._restyle(self.dup_label)
        self.dup_label.setText(
            f"{I.STOP}  Nieobsługiwany adres. Wklej link do lekcji w formacie:\n"
            f"{SUPPORTED_URL_HINT}"
        )
        if not self.dup_label.isVisible():
            anim.fade_in(self.dup_label, ms=anim.BASE)
        self.log(f"Nieobsługiwany adres — dozwolone tylko: {SUPPORTED_URL_HINT}")

    def _reset_pending(self) -> None:
        """Cofa pytanie o duplikat: napis przycisku wraca na swoje miejsce."""
        self._pending = None
        if self.dup_label.isVisible():
            anim.fade_out(self.dup_label)
        if self._state in (self.IDLE, self.DONE, self.REVIEW):
            self._set_main_button(DOWNLOAD_TEXT, "DOWNLOAD")
        self.download_btn.setObjectName("Primary")
        self._restyle(self.download_btn)

    def _warn_duplicate(self, url: str, existing: dict) -> None:
        """Ten adres już raz pobrano — czekamy na świadome potwierdzenie."""
        self._pending = url
        self.dup_label.setObjectName("Warn")
        self._restyle(self.dup_label)
        source = ("dopisano już jako tablice do lekcji"
                  if existing.get("appended") else "pobrano już jako lekcję")
        action = "Dopisz mimo to" if self._append_target else "Kontynuuj"
        self.dup_label.setText(
            f"{I.WARN}  Ten URL {source} #{existing['number']} "
            f"({existing['topic']}, {existing['downloaded_at']}). "
            f"Kliknij „{action}”, aby pobrać go ponownie."
        )
        anim.fade_in(self.dup_label, ms=anim.BASE)
        self._set_main_button(f"  {action}", "REFRESH")
        self.log("Wykryto pobraną wcześniej lekcję. "
                 "Oczekuję na potwierdzenie kontynuacji.")

    # ────────────────────────────── tryb dopisywania

    def _on_append_toggled(self, checked: bool) -> None:
        """Zaznaczenie pyta o lekcję; rezygnacja w oknie cofa zaznaczenie."""
        if not checked:
            self._set_append_target(None)
            return
        target = self._choose_lesson()
        if target is None:
            self._set_checked(False)
            return
        self._set_append_target(target)

    def _set_checked(self, checked: bool) -> None:
        """Ustawia pole wyboru bez wywoływania `toggled` (uniknięcie pętli)."""
        self.append_check.blockSignals(True)
        self.append_check.setChecked(checked)
        self.append_check.blockSignals(False)

    def _choose_lesson(self) -> Optional[dict]:
        """Pyta, do której lekcji dopisać tablice. None = użytkownik odpuścił."""
        lessons = load_history().get("lessons", [])
        if not lessons:
            self.dup_label.setObjectName("Err")
            self._restyle(self.dup_label)
            self.dup_label.setText(
                f"{I.STOP}  Historia jest pusta — nie ma do czego dopisywać. "
                f"Pobierz najpierw lekcję przyciskiem „Pobierz”."
            )
            if not self.dup_label.isVisible():
                anim.fade_in(self.dup_label, ms=anim.BASE)
            self.log("Brak lekcji w historii — dopisywanie niemożliwe.")
            return None

        # Najświeższa lekcja na górze listy: to do niej dopisuje się najczęściej.
        lessons.sort(key=lambda x: (x.get("number", 0),
                                    x.get("downloaded_at", "")), reverse=True)
        dlg = LessonPickerDialog(self.window(), lessons, self._config)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.log("Dopisywanie anulowane.")
            return None
        return dlg.selected()

    def _set_append_target(self, lesson: Optional[dict]) -> None:
        """Ustawia (albo zdejmuje) cel dopisywania i podpis pod kartą URL."""
        self._append_target = lesson
        if lesson is None:
            self._set_checked(False)
            if self.append_note.isVisible():
                anim.fade_out(self.append_note)
            return
        self._set_checked(True)
        topic = lesson.get("topic", "")
        nice = "" if topic in NO_TOPIC else f" ({topic})"
        self.append_note.setText(
            f"Tablice trafią do lekcji #{lesson.get('number', '?')}{nice} — "
            f"numer lekcji i licznik kolejnych pozostaną bez zmian."
        )
        if not self.append_note.isVisible():
            anim.fade_in(self.append_note, ms=anim.BASE)

    def _busy_title(self) -> str:
        """Nagłówek paska postępu — zależny od trybu, bo tryby robią co innego."""
        if self._append_target is not None:
            num = self._append_target.get("number", "?")
            return f"{I.DOWNLOAD}   Dopisywanie tablic do lekcji #{num}…"
        return f"{I.DOWNLOAD}   Pobieranie obrazów…"

    def _sync_review_mode(self) -> None:
        """Dostraja kartę podglądu do trybu: nowa lekcja vs dopisywanie tablic."""
        lesson = self._append_target
        if lesson is None:
            self.review_title.setText("Podgląd obrazów")
            self.topic_title.setText(f"{I.TOPIC}  Temat lekcji")
            self.topic_edit.setEnabled(True)
            self.topic_edit.setPlaceholderText("Wpisz temat lekcji…")
            self.topic_hint.setText("Możesz wpisać temat lub pozostawić puste.")
            self.confirm_btn.setText("  Zatwierdź i pobierz")
            return

        num = lesson.get("number", "?")
        topic = lesson.get("topic", "")
        self.review_title.setText(f"Podgląd tablic do dopisania (lekcja #{num})")
        self.topic_title.setText(f"{I.TOPIC}  Lekcja docelowa")
        # Temat jest własnością lekcji docelowej — dopisywane tablice nie mogą
        # zmienić nazwy jej folderu, więc pole tylko informuje.
        self.topic_edit.setEnabled(False)
        self.topic_edit.setText("" if topic in NO_TOPIC else topic)
        self.topic_edit.setPlaceholderText(f"Lekcja #{num} — bez tematu")
        self.topic_hint.setText(
            f"Obrazy dostaną dalsze numery w folderze lekcji #{num}. "
            f"Temat i numeracja lekcji zostają bez zmian."
        )
        self.confirm_btn.setText(f"  Dopisz do lekcji #{num}")

    def _start_phase1(self, url: str) -> None:
        self._hide_timer.stop()
        self._set_state(self.LOADING)
        self.log("━" * 50)
        self.log(f"Rozpoczynam pobieranie: {url}")
        self.log("━" * 50)

        self._job = workers.Phase1Job(url, self._config,
                                      append_lesson=self._append_target)
        self._job.log.connect(self.log)
        self._job.done.connect(self._on_phase1_done)
        self._job.failed.connect(self._on_phase1_failed)
        self._job.start()

    def _on_phase1_failed(self, err: str) -> None:
        self.log(f"\nBłąd: {err}")
        self._set_state(self.IDLE)

    def _on_phase1_done(self, result: Phase1Result) -> None:
        self._phase1 = result
        self._preview_bytes.clear()
        self._preview_idx = 0

        if not result.image_urls:
            self.log("\nBrak obrazów — nie można kontynuować.")
            self._set_state(self.IDLE)
            return

        self.topic_edit.clear()
        self._update_nav()
        self._set_state(self.REVIEW)

        if result.first_image_bytes:
            self._preview_bytes[0] = result.first_image_bytes
            QTimer.singleShot(60, self._autosize_then_show)
        else:
            # Pierwszy obraz nie dojechał w fazie 1 (chwilowy błąd sieci).
            # Bez tego podgląd zostawał pusty, dopóki użytkownik sam nie
            # przewinął galerii — wyglądało to na zepsute pobieranie.
            self.preview.setText("Pobieranie…")
            self._start_image_job(0)

    def _autosize_then_show(self) -> None:
        data = self._preview_bytes.get(self._preview_idx)
        if not data:
            return
        pm = QPixmap()
        pm.loadFromData(QByteArray(data))
        if pm.isNull():
            return
        # Wysokość okna dopasowana do proporcji obrazu — Qt animuje geometrię płynnie.
        avail_w = max(320, self.preview.width() or 560)
        want_h = int(avail_w * pm.height() / max(1, pm.width()))
        want_h = max(PREVIEW_MIN_H, min(want_h, PREVIEW_MAX_H))
        extra = want_h - self.preview.height()
        if extra > 12:
            self.request_height.emit(extra)
        QTimer.singleShot(anim.SLOW + 40, lambda: self._show_preview(fade=True))

    # ────────────────────────────── galeria

    def _pixmap_for(self, idx: int) -> Optional[QPixmap]:
        data = self._preview_bytes.get(idx)
        if not data:
            return None
        pm = QPixmap()
        pm.loadFromData(QByteArray(data))
        return None if pm.isNull() else pm

    def _rescale_preview(self) -> None:
        pm = self._pixmap_for(self._preview_idx)
        if pm is None or self.preview.width() < 40:
            return
        self.preview.setPixmap(pm.scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _show_preview(self, *, fade: bool = False) -> None:
        pm = self._pixmap_for(self._preview_idx)
        if pm is None:
            self.preview.setText("(brak podglądu)")
            return
        self.preview.setText("")
        if fade:
            self._rescale_preview()
            anim.fade_in(self.preview, ms=anim.BASE)
        else:
            self._rescale_preview()

    def _change_preview(self, direction: int) -> None:
        if not self._phase1 or not self._phase1.image_urls:
            return
        total = len(self._phase1.image_urls)
        new_idx = self._preview_idx + direction
        if not (0 <= new_idx < total):
            return
        self._preview_idx = new_idx
        self._update_nav()

        if new_idx in self._preview_bytes:
            anim.cross_fade(self.preview, lambda: self._show_preview())
            return

        anim.cross_fade(self.preview,
                        lambda: self.preview.setText("Pobieranie…"))
        self._start_image_job(new_idx)

    def _start_image_job(self, idx: int) -> None:
        """Dociąga obraz do podglądu (jeden wątek na indeks).

        Bez straży szybkie klikanie „dalej/wstecz" podmieniało referencję na
        wciąż pracującym zadaniu — obiekt szedł do kosza w trakcie emisji
        sygnału z wątku roboczego.
        """
        if not self._phase1 or idx in self._img_jobs:
            return
        job = workers.ImageJob(idx, self._phase1.image_urls[idx],
                               self._phase1.headers)
        job.done.connect(self._on_image_loaded)
        self._img_jobs[idx] = job        # trzymaj referencję
        job.start()

    def _on_image_loaded(self, idx: int, data) -> None:
        self._img_jobs.pop(idx, None)
        if data:
            self._preview_bytes[idx] = data
        if idx != self._preview_idx:
            return
        if data:
            anim.cross_fade(self.preview, lambda: self._show_preview())
        else:
            self.preview.setText("(brak podglądu)")

    def _update_nav(self) -> None:
        if not self._phase1:
            return
        total = len(self._phase1.image_urls)
        self.idx_label.setText(f"{self._preview_idx + 1} / {total}")
        self.prev_btn.setEnabled(self._preview_idx > 0)
        self.next_btn.setEnabled(self._preview_idx < total - 1)

    def _on_cancel(self) -> None:
        self.log("Anulowano pobieranie przez użytkownika.")
        self._phase1 = None
        self._preview_bytes.clear()
        self.preview.clear()
        self._set_state(self.IDLE)

    # ────────────────────────────── Phase 2

    def _on_confirm(self) -> None:
        # Cel dopisywania trzeba zapamiętać przed zmianą stanu: to on decyduje
        # o wariancie fazy 2, a podpisy paska postępu czytają go dalej.
        lesson = self._append_target
        if lesson is not None:
            self.log(f"Dopisywanie do lekcji #{lesson.get('number', '?')} "
                     f"({lesson.get('topic', '') or 'bez tematu'}).")
            self._set_state(self.DOWNLOADING)
            self._job = workers.Phase2AppendJob(self._current_url, lesson,
                                                self._phase1, self._config)
        else:
            topic = sanitize_filename(
                self.topic_edit.text().strip() or "Bez_tematu")
            self.log(f"Zatwierdzony temat: {topic}")
            self._set_state(self.DOWNLOADING)
            self._job = workers.Phase2Job(self._current_url, topic,
                                          self._phase1, self._config)

        self._job.log.connect(self.log)
        self._job.progress.connect(self._on_progress)
        self._job.done.connect(self._on_phase2_done)
        self._job.failed.connect(self._on_phase2_failed)
        self._job.start()

    def _on_progress(self, pct: float) -> None:
        total = len(self._phase1.image_urls) if self._phase1 else 0
        current = max(1, round(pct * total))
        pct_i = int(round(pct * 100))
        self.status_sub.setText(f"Obraz {current} z {total}" if total else "")
        self.status_pct.setText(f"{pct_i}%")
        self.status_title.setText(f"{self._busy_title()} {pct_i}%")

        a = QPropertyAnimation(self.progress, QByteArray(b"value"), self)
        a.setDuration(anim.FAST)
        a.setStartValue(self.progress.value())
        a.setEndValue(int(pct * 1000))
        a.setEasingCurve(anim.EASE_OUT)
        anim._keep(self.progress, a, "_val_anim")
        a.start()

    def _on_phase2_failed(self, err: str) -> None:
        self.log(f"\nBłąd pobierania: {err}")
        self._set_state(self.IDLE)

    def _on_phase2_done(self, result: LessonResult) -> None:
        added = result.downloaded_images
        self.status_title.setText(
            f"{I.OK}   Dopisano do lekcji #{result.lesson_number}"
            if result.appended else f"{I.OK}   Pobieranie zakończone")
        self.status_sub.setText(
            f"Dopisano {added} {boards_word(added)} z {result.total_images}"
            if result.appended else "")
        self.status_pct.setText("100%")
        self.status_pct.setObjectName("StatusPctDone")
        self._restyle(self.status_pct)
        self.progress.setObjectName("Done")
        self._restyle(self.progress)

        a = QPropertyAnimation(self.progress, QByteArray(b"value"), self)
        a.setDuration(anim.BASE)
        a.setStartValue(self.progress.value())
        a.setEndValue(1000)
        a.setEasingCurve(anim.EASE_OUT)
        anim._keep(self.progress, a, "_val_anim")
        a.start()

        while self.paths_layout.count():
            it = self.paths_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        dirs: list[str] = []
        for path_str, ok, _ in result.save_results:
            if ok:
                d = os.path.dirname(path_str)
                if d not in dirs:
                    dirs.append(d)

        if dirs:
            self.paths_layout.addWidget(label(
                f"{I.OK}  Dopisano w folderach:" if result.appended
                else f"{I.OK}  Zapisano w folderach:", "FieldTitle"))
            self.paths_box.show()
            anim.stagger(dirs, self._add_path_row, first=80, step=70)

        self.log("\n" + "━" * 50)
        if result.appended:
            last = result.first_index + added - 1
            self.log("  Dopisywanie zakończone!")
            self.log(f"  Lekcja:   #{result.lesson_number}")
            self.log(f"  Temat:    {result.topic}")
            self.log(f"  Tablic:   {added}/{result.total_images} "
                     f"(numery {result.first_index:02d}–{last:02d})")
        else:
            self.log("  Pobieranie zakończone!")
            self.log(f"  Lekcja:  #{result.lesson_number}")
            self.log(f"  Temat:   {result.topic}")
            self.log(f"  Obrazów: {added}/{result.total_images}")
        self.log("━" * 50)

        self._set_state(self.DONE)
        self.history_changed.emit()

        if result.appended:
            # Pasek statusu znika po chwili, a to jedyne potwierdzenie, że
            # tablice trafiły do STAREJ lekcji, a nie do nowej.
            Toast.show_at(
                self.window(),
                f"{I.OK}  Dopisano {added} {boards_word(added)} "
                f"do lekcji #{result.lesson_number}", C.SUCCESS, ms=3200)
            self._set_append_target(None)

        self._hide_timer.start(STATUS_AUTOHIDE_MS)

    def _add_path_row(self, d: str, _i: int) -> None:
        row = QWidget(self.paths_box)
        rl = hbox(row, s=PAD_SM)
        rl.addWidget(label(d, "Muted"), 1)
        btn = QPushButton(f"{I.OPEN}  Otwórz", row)
        btn.setObjectName("CardAction")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: subprocess.Popen(f'explorer "{d}"'))
        rl.addWidget(btn)
        self.paths_layout.addWidget(row)
        anim.pop_in(row, ms=anim.BASE)

    def _hide_status(self) -> None:
        self.status_pct.setObjectName("StatusPct")
        self._restyle(self.status_pct)
        self.progress.setObjectName("")
        self._restyle(self.progress)
        anim.fade_out(self.status_card, ms=anim.BASE,
                      on_done=self.status_card.hide)
        anim.fade_out(self.paths_box, ms=anim.BASE, on_done=self.paths_box.hide)
