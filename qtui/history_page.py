"""Mathloader — zakładka „Historia" (Qt)."""
from __future__ import annotations

import subprocess
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFrame, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget,
)

from config import AppConfig
from downloader import (
    delete_lesson, is_link_expired, lesson_expiry, load_history, save_history,
)
from qtui import anim
from qtui.theme import C, I, PAD_LG, PAD_MD, PAD_SM, PAD_XL, PAD_XXL
from qtui.widgets import ConfirmDialog, Toast, card, hbox, label, vbox

SORTS = ["Najnowsze najpierw", "Najstarsze najpierw", "Nazwa: A-Z", "Nazwa: Z-A"]


class LessonCard(QFrame):
    """Karta pojedynczej lekcji."""

    deleted = Signal(object)     # lesson dict

    def __init__(self, lesson: dict, config: AppConfig,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._lesson = lesson
        self._config = config
        self._url = lesson.get("url", "")
        self._short = self._url[:64] + "…" if len(self._url) > 64 else self._url
        self._copied = False

        # Wygaśnięcie liczone od DATY UTWORZENIA lekcji (created_at), a nie od
        # chwili pobrania — link na serwerze żyje tydzień od powstania lekcji.
        self._expired = is_link_expired(lesson)
        exp = lesson_expiry(lesson)
        self._expiry_str = exp.strftime("%Y-%m-%d %H:%M") if exp else ""
        date = lesson.get("created_at") or lesson.get("downloaded_at", "")

        lay = vbox(self, m=PAD_LG, s=PAD_SM)

        # górny wiersz: numer + temat
        top = QWidget(self)
        tl = hbox(top, s=PAD_MD)
        num = label(f"#{lesson.get('number', '?')}", "SectionTitle")
        num.setStyleSheet(f"color: {C.PRIMARY};")
        num.setFixedWidth(52)
        tl.addWidget(num)

        topic = lesson.get("topic", "")
        empty = not topic or topic in ("Bez_tematu", "*Bez Tematu*", "Bez Tematu")
        tw = label("Bez tematu" if empty else topic, "FieldTitle")
        if empty:
            f = tw.font(); f.setItalic(True); tw.setFont(f)
            tw.setStyleSheet(f"color: {C.TEXT_MUTED};")
        tl.addWidget(tw, 1)
        lay.addWidget(top)

        # dolny wiersz: data + URL + akcje
        bottom = QWidget(self)
        bl = hbox(bottom, s=PAD_SM)
        d = label(date, "Muted")
        d.setFixedWidth(150)
        if self._expiry_str:
            d.setToolTip(
                f"Link wygasł: {self._expiry_str}" if self._expired
                else f"Link ważny do: {self._expiry_str}")
        bl.addWidget(d)

        self.url_btn = QPushButton(self._short, bottom)
        self.url_btn.setObjectName(
            "UrlChipExpired" if self._expired else "UrlChip")
        if self._expired:
            f = self.url_btn.font(); f.setStrikeOut(True); self.url_btn.setFont(f)
            self.url_btn.setToolTip(
                f"Link wygasł {self._expiry_str} (tydzień od utworzenia lekcji)")
        else:
            self.url_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.url_btn.clicked.connect(self._copy_url)
        self.url_btn.enterEvent = self._on_enter          # type: ignore[method-assign]
        self.url_btn.leaveEvent = self._on_leave          # type: ignore[method-assign]
        bl.addWidget(self.url_btn, 1)

        self.open_btn = QPushButton(f"{I.OPEN}  Otwórz", bottom)
        self.open_btn.setObjectName("CardAction")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_folder)
        bl.addWidget(self.open_btn)

        self.del_btn = QPushButton(I.CROSS, bottom)
        self.del_btn.setObjectName("IconDanger")
        self.del_btn.setFixedWidth(38)
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_btn.setToolTip("Usuń z historii  (Shift = bez potwierdzenia)")
        self.del_btn.clicked.connect(self._on_delete)
        bl.addWidget(self.del_btn)

        lay.addWidget(bottom)

    # ── hover na URL ──
    def _on_enter(self, e) -> None:
        if self._copied:
            return
        self.url_btn.setText("Link wygasły" if self._expired else "Skopiuj link")
        f = self.url_btn.font(); f.setItalic(True); self.url_btn.setFont(f)

    def _on_leave(self, e) -> None:
        if self._copied:
            return
        self.url_btn.setText(self._short)
        f = self.url_btn.font(); f.setItalic(False); self.url_btn.setFont(f)

    def _copy_url(self) -> None:
        if self._expired or not self._url:
            return
        QGuiApplication.clipboard().setText(self._url)
        self._copied = True
        self.url_btn.setText(f"{I.CHECK}  Skopiowano")
        self.url_btn.setStyleSheet(
            f"color: {C.SUCCESS}; border-color: {C.SUCCESS};")

        def _restore() -> None:
            self._copied = False
            self.url_btn.setStyleSheet("")
            f = self.url_btn.font(); f.setItalic(False); self.url_btn.setFont(f)
            self.url_btn.setText(self._short)

        QTimer.singleShot(1500, _restore)

    def _open_folder(self) -> None:
        topic = self._lesson.get("topic", "Bez_tematu")
        num = self._lesson.get("number", 1)
        folder = self._config.format_folder_name(num, topic)
        opened = False
        for base in self._config.save_paths:
            full = base / folder
            if full.exists():
                subprocess.Popen(["explorer", str(full)])
                opened = True
                break
        if not opened:
            paths = self._config.save_paths
            if paths and paths[0].exists():
                subprocess.Popen(["explorer", str(paths[0])])
                opened = True
        self.open_btn.setText(f"{I.CHECK}  OK" if opened else "—")
        QTimer.singleShot(
            1500, lambda: self.open_btn.setText(f"{I.OPEN}  Otwórz"))

    def _on_delete(self) -> None:
        shift = bool(QGuiApplication.keyboardModifiers()
                     & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            self._do_delete()
            return
        num = self._lesson.get("number", "?")
        topic = self._lesson.get("topic", "")
        nice = (f"lekcję #{num} — {topic}"
                if topic and topic not in ("Bez_tematu", "Bez Tematu")
                else f"lekcję #{num}")
        dlg = ConfirmDialog(
            self.window(),
            title="Potwierdzenie",
            message=f"Czy na pewno chcesz usunąć z historii\n{nice}?",
            hint="Wskazówka: przytrzymaj Shift przy kliknięciu „✕”, "
                 "aby usuwać bez tego pytania.",
            confirm_text="Usuń lekcję",
        )
        if dlg.exec() == ConfirmDialog.DialogCode.Accepted:
            self._do_delete()

    def _do_delete(self) -> None:
        anim.slide_up(self, ms=anim.FAST,
                      on_done=lambda: self.deleted.emit(self._lesson))


class HistoryPage(QWidget):
    """Lista pobranych lekcji."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        self._sort = SORTS[0]
        self._gen = 0
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = vbox(self, m=PAD_LG, s=PAD_MD)

        head = QWidget(self)
        hl = hbox(head, s=PAD_MD)
        self.count_label = label(f"{I.LIST}  Pobrane lekcje", "SectionTitle")
        hl.addWidget(self.count_label, 1)

        self.sort_combo = QComboBox(head)
        self.sort_combo.addItems(SORTS)
        self.sort_combo.setFixedWidth(180)
        self.sort_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sort_combo.currentTextChanged.connect(self._on_sort)
        hl.addWidget(self.sort_combo)

        self.clear_btn = QPushButton(f"{I.ERASE}  Wyczyść historię", head)
        self.clear_btn.setObjectName("CardAction")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear_history)
        hl.addWidget(self.clear_btn)
        root.addWidget(head)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QFrame()
        holder.setObjectName("Surface")
        self.list_layout = vbox(holder, m=PAD_MD, s=PAD_SM)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(holder)
        root.addWidget(self.scroll, 1)

    # ── dane ──

    def _on_sort(self, value: str) -> None:
        self._sort = value
        self.refresh()

    def _clear_rows(self) -> None:
        while self.list_layout.count() > 1:     # zostaw stretch
            it = self.list_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def refresh(self) -> None:
        self._clear_rows()
        self._gen += 1
        gen = self._gen

        lessons = load_history().get("lessons", [])
        if not lessons:
            self.count_label.setText(f"{I.LIST}  Pobrane lekcje (0)")
            empty = label(
                f"{I.LIST}\n\nBrak pobranych lekcji.\n"
                f"Przejdź do zakładki „Pobierz”.",
                "Muted", wrap=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {C.TEXT_MUTED}; padding: {PAD_XXL}px;")
            self.list_layout.insertWidget(0, empty)
            anim.fade_in(empty, ms=anim.SLOW)
            return

        self.count_label.setText(f"{I.LIST}  Pobrane lekcje ({len(lessons)})")

        if self._sort == SORTS[0]:
            lessons.sort(key=lambda x: x.get("downloaded_at", ""), reverse=True)
        elif self._sort == SORTS[1]:
            lessons.sort(key=lambda x: x.get("downloaded_at", ""))
        elif self._sort == SORTS[2]:
            lessons.sort(key=lambda x: x.get("topic", "").lower())
        else:
            lessons.sort(key=lambda x: x.get("topic", "").lower(), reverse=True)

        def add(lesson, i) -> None:
            if gen != self._gen:
                return
            c = LessonCard(lesson, self._config)
            c.deleted.connect(self._on_card_deleted)
            self.list_layout.insertWidget(self.list_layout.count() - 1, c)
            anim.pop_in(c, ms=anim.BASE)

        anim.stagger(lessons, add, first=0, step=45, cap=12)

    def _on_card_deleted(self, lesson: dict) -> None:
        history = load_history()
        delete_lesson(history, lesson)
        self.refresh()

    def _clear_history(self) -> None:
        dlg = ConfirmDialog(
            self.window(),
            title="Potwierdzenie",
            message="Czy na pewno chcesz usunąć całą historię?",
            hint="Tej operacji nie można cofnąć.",
            confirm_text="Usuń historię",
        )
        if dlg.exec() == ConfirmDialog.DialogCode.Accepted:
            save_history({"lessons": [], "next_number": 1})
            self.refresh()
            Toast.show_at(self.window(), f"{I.CHECK}  Historia wyczyszczona")
