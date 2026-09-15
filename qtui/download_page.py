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
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from config import AppConfig
from downloader import (
    SUPPORTED_URL_HINT, LessonResult, Phase1Result, find_existing_lesson,
    is_supported_url, load_history, sanitize_filename,
)
from qtui import anim, workers
from qtui.theme import (
    C, I, PAD_LG, PAD_MD, PAD_SM, PAD_XL, RADIUS_SM,
)
from qtui.widgets import card, hbox, label, vbox

PREVIEW_MIN_H = 220
PREVIEW_MAX_H = 820
CONSOLE_COLLAPSED = 58
CONSOLE_EXPANDED = 300
STATUS_AUTOHIDE_MS = 20000


class DownloadPage(QWidget):
    """Główny widok pracy: URL → podgląd → pobieranie."""

    IDLE, LOADING, REVIEW, DOWNLOADING, DONE = range(5)

    request_height = Signal(int)     # sugerowana wysokość okna
    history_changed = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        self._state = self.IDLE
        self._phase1: Optional[Phase1Result] = None
        self._current_url = ""
        self._download_allowed = True
        self._awaiting_dup = False
        self._preview_bytes: dict[int, bytes] = {}
        self._preview_idx = 0
        self._console_expanded = False
        self._hide_timer: Optional[QTimer] = None
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

        self.download_btn = QPushButton(f"{I.DOWNLOAD}   Pobierz", row)
        self.download_btn.setObjectName("Primary")
        self.download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_btn.setMinimumWidth(160)
        self.download_btn.clicked.connect(self._on_download)
        rl.addWidget(self.download_btn)
        ucl.addWidget(row)

        self.dup_label = label("", "Hint", wrap=True)
        self.dup_label.setStyleSheet(f"color: {C.WARNING};")
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
        self.status_pct = label("", "Hint")
        self.status_pct.setStyleSheet(f"color: {C.PRIMARY}; font-weight: 700;")
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
        lay.addWidget(label("Podgląd obrazów", "FieldTitle"))

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
        self.prev_btn = QPushButton(I.ARROW_L, nav)
        self.prev_btn.setObjectName("CardAction")
        self.prev_btn.setFixedWidth(44)
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self._change_preview(-1))

        self.idx_label = label("1 / 1", "Muted")
        self.idx_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.next_btn = QPushButton(I.ARROW_R, nav)
        self.next_btn.setObjectName("CardAction")
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
        tl.addWidget(label(f"{I.NAME_TAG}  Temat lekcji", "FieldTitle"))

        self.topic_edit = QLineEdit(topic)
        self.topic_edit.setPlaceholderText("Wpisz temat lekcji…")
        self.topic_edit.returnPressed.connect(self._on_confirm)
        tl.addWidget(self.topic_edit)

        tl.addWidget(label("Możesz wpisać temat lub pozostawić puste.",
                           "Muted", wrap=True))
        tl.addStretch(1)

        self.confirm_btn = QPushButton(f"{I.CHECK}   Zatwierdź i pobierz", topic)
        self.confirm_btn.setObjectName("Success")
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
        hl.addWidget(label(f"{I.SLIDERS}  Konsola", "Hint"))
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

    def set_download_enabled(self, enabled: bool) -> None:
        self._download_allowed = enabled
        if self._state in (self.IDLE, self.DONE):
            self.download_btn.setEnabled(enabled)

    def _set_state(self, state: int) -> None:
        self._state = state
        idle_like = state in (self.IDLE, self.DONE)
        self.url_edit.setEnabled(idle_like)
        self.download_btn.setEnabled(idle_like and self._download_allowed)

        if state == self.IDLE:
            self.download_btn.setText(f"{I.DOWNLOAD}   Pobierz")
            anim.fade_out(self.status_card, on_done=self.status_card.hide)
            anim.fade_out(self.review_card, on_done=self.review_card.hide)
            self.dup_label.hide()
            self.request_height.emit(0)

        elif state == self.LOADING:
            self.download_btn.setText("Ładowanie…")
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
            self.download_btn.setText(f"{I.DOWNLOAD}   Pobierz")
            self.status_card.hide()
            anim.reveal(self.review_card, ms=anim.BASE)

        elif state == self.DOWNLOADING:
            self.download_btn.setText("Pobieranie…")
            self.review_card.hide()
            self.progress.setRange(0, 1000)
            self.progress.setValue(0)
            self.status_title.setText(f"{I.DOWNLOAD}   Pobieranie obrazów…")
            self.status_pct.setText("0%")
            self.status_sub.setText("")
            anim.reveal(self.status_card, ms=anim.BASE)

        elif state == self.DONE:
            self.download_btn.setText(f"{I.REFRESH}   Nowe pobieranie")
            self.request_height.emit(0)

    # ────────────────────────────── Phase 1

    def _on_url_changed(self, text: str) -> None:
        if self._awaiting_dup and text.strip() != self._current_url:
            self._awaiting_dup = False
            anim.fade_out(self.dup_label)
            self.download_btn.setText(f"{I.DOWNLOAD}   Pobierz")
            self.download_btn.setObjectName("Primary")
            self._restyle(self.download_btn)
        elif not self._awaiting_dup and self.dup_label.isVisible():
            # schowaj komunikat o nieobsługiwanym adresie po edycji
            anim.fade_out(self.dup_label)

    def _restyle(self, w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)

    def _on_download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self.log("Podaj URL strony z lekcją.")
            return

        if not is_supported_url(url):
            self._awaiting_dup = False
            self.download_btn.setText(f"{I.DOWNLOAD}   Pobierz")
            self.download_btn.setObjectName("Primary")
            self._restyle(self.download_btn)
            self.dup_label.setStyleSheet(f"color: {C.ERROR};")
            self.dup_label.setText(
                f"{I.STOP}  Nieobsługiwany adres. Wklej link do lekcji w formacie:\n"
                f"{SUPPORTED_URL_HINT}"
            )
            if not self.dup_label.isVisible():
                anim.fade_in(self.dup_label, ms=anim.BASE)
            self.log(f"Nieobsługiwany adres — dozwolone tylko: {SUPPORTED_URL_HINT}")
            return

        if self._awaiting_dup and self._current_url == url:
            self._awaiting_dup = False
            anim.fade_out(self.dup_label)
            self.download_btn.setObjectName("Primary")
            self._restyle(self.download_btn)
            self._start_phase1(url)
            return

        self._current_url = url
        self._clear_log()
        self._awaiting_dup = False
        self.paths_box.hide()

        existing = find_existing_lesson(load_history(), url)
        if existing:
            self._awaiting_dup = True
            self.dup_label.setStyleSheet(f"color: {C.WARNING};")
            self.dup_label.setText(
                f"{I.WARN}  Ten URL pobrano wcześniej: lekcja #{existing['number']} "
                f"({existing['topic']}, {existing['downloaded_at']}). "
                f"Kliknij „Kontynuuj”, aby pobrać ponownie."
            )
            anim.fade_in(self.dup_label, ms=anim.BASE)
            self.download_btn.setText(f"{I.REFRESH}   Kontynuuj")
            self.log("Wykryto pobraną wcześniej lekcję. "
                     "Oczekuję na potwierdzenie kontynuacji.")
            return

        self._start_phase1(url)

    def _start_phase1(self, url: str) -> None:
        if self._hide_timer:
            self._hide_timer.stop()
        self._set_state(self.LOADING)
        self.log("━" * 50)
        self.log(f"Rozpoczynam pobieranie: {url}")
        self.log("━" * 50)

        self._job = workers.Phase1Job(url, self._config)
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
        job = workers.ImageJob(new_idx, self._phase1.image_urls[new_idx],
                               self._phase1.headers)
        job.done.connect(self._on_image_loaded)
        self._img_jobs[new_idx] = job    # trzymaj referencję
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
        topic = sanitize_filename(self.topic_edit.text().strip() or "Bez_tematu")
        self.log(f"Zatwierdzony temat: {topic}")
        self._set_state(self.DOWNLOADING)

        self._job = workers.Phase2Job(self._current_url, topic, self._phase1,
                                      self._config)
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
        self.status_title.setText(f"{I.DOWNLOAD}   Pobieranie obrazów… {pct_i}%")

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
        self.status_title.setText(f"{I.CHECK}   Pobieranie zakończone")
        self.status_sub.setText("")
        self.status_pct.setText("100%")
        self.status_pct.setStyleSheet(f"color: {C.SUCCESS}; font-weight: 700;")
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
            self.paths_layout.addWidget(
                label(f"{I.CHECK}  Zapisano w folderach:", "FieldTitle"))
            self.paths_box.show()
            anim.stagger(dirs, self._add_path_row, first=80, step=70)

        self.log("\n" + "━" * 50)
        self.log("  Pobieranie zakończone!")
        self.log(f"  Lekcja:  #{result.lesson_number}")
        self.log(f"  Temat:   {result.topic}")
        self.log(f"  Obrazów: {result.downloaded_images}/{result.total_images}")
        self.log("━" * 50)

        self._set_state(self.DONE)
        self.history_changed.emit()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_status)
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
        self.status_pct.setStyleSheet(f"color: {C.PRIMARY}; font-weight: 700;")
        self.progress.setObjectName("")
        self._restyle(self.progress)
        anim.fade_out(self.status_card, ms=anim.BASE,
                      on_done=self.status_card.hide)
        anim.fade_out(self.paths_box, ms=anim.BASE, on_done=self.paths_box.hide)
