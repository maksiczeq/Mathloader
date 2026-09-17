"""Mathloader — zakładka „Historia" (Qt)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFrame, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget,
)

from config import AppConfig
from downloader import (
    delete_lesson, is_link_expired, lesson_expiry, load_history, save_history,
)
from qtui import anim
from qtui.theme import C, G, I, PAD_LG, PAD_MD, PAD_SM
from qtui.widgets import ConfirmDialog, Toast, hbox, label, restyle, vbox

SORTS = ["Najnowsze najpierw", "Najstarsze najpierw", "Nazwa: A-Z", "Nazwa: Z-A"]

# Kaskada wejścia listy: ile kart animować i co ile milisekund.
FADE_STEP = 40
FADE_CAP = 10


def lesson_folders(lesson: dict, config: AppConfig) -> list[Path]:
    """Foldery, w których leży ta lekcja.

    Pobieranie zapisuje realne ścieżki w historii (`folders`). Starsze wpisy
    ich nie mają — dla nich nazwę trzeba odtworzyć z aktualnego szablonu, co
    się rozjedzie, jeśli użytkownik zmienił format nazw po pobraniu.
    """
    stored = [Path(f) for f in lesson.get("folders", []) if f]
    if stored:
        return stored
    name = config.format_folder_name(lesson.get("number", 1),
                                     lesson.get("topic", ""))
    return [base / name for base in config.save_paths]


def pick_lesson_folder(lesson: dict, config: AppConfig) -> Optional[Path]:
    """Folder do otwarcia: najpierw kopia w ścieżce domyślnej, potem reszta.

    Dzięki temu „Otwórz" trafia tam, gdzie użytkownik ustawił domyślny zapis,
    a nie w pierwszy lepszy nośnik — a gdy ten akurat jest odłączony, sięga po
    kolejną istniejącą kopię zamiast zgłaszać brak plików.
    """
    existing = [f for f in lesson_folders(lesson, config) if f.exists()]
    if not existing:
        return None
    default = config.default_save_path
    if default is not None:
        for folder in existing:
            if folder.parent == default:
                return folder
    return existing[0]


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
        self._deleting = False

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
        num = label(f"#{lesson.get('number', '?')}",
                    "LessonNumberExpired" if self._expired else "LessonNumber")
        num.setFixedWidth(52)
        tl.addWidget(num)

        topic = lesson.get("topic", "")
        empty = not topic or topic in ("Bez_tematu", "*Bez Tematu*", "Bez Tematu")
        tw = label("Bez tematu" if empty else topic,
                   "NoTopic" if empty else "FieldTitle")
        if empty:
            f = tw.font(); f.setItalic(True); tw.setFont(f)
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

        self.del_btn = QPushButton(G.CLOSE, bottom)
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
        self.url_btn.setText(f"{I.OK}  Skopiowano")
        self.url_btn.setObjectName("UrlChipCopied")
        restyle(self.url_btn)

        def _restore() -> None:
            self._copied = False
            self.url_btn.setObjectName("UrlChip")
            restyle(self.url_btn)
            f = self.url_btn.font(); f.setItalic(False); self.url_btn.setFont(f)
            self.url_btn.setText(self._short)

        QTimer.singleShot(1500, _restore)

    def _open_folder(self) -> None:
        """Otwiera folder lekcji — z pierwszeństwem dla ścieżki domyślnej."""
        folder = pick_lesson_folder(self._lesson, self._config)
        if folder is not None:
            subprocess.Popen(["explorer", str(folder)])
            self.open_btn.setText(f"{I.OK}  OK")
            QTimer.singleShot(
                1500, lambda: self.open_btn.setText(f"{I.OPEN}  Otwórz"))
            return

        # Żadna kopia nie istnieje: pliki skasowano albo nośnik jest odłączony.
        # Cisza byłaby tu najgorsza — użytkownik zobaczyłby „—" bez powodu.
        self.open_btn.setText("—")
        QTimer.singleShot(
            1800, lambda: self.open_btn.setText(f"{I.OPEN}  Otwórz"))
        Toast.show_at(
            self.window(),
            f"{I.WARN}  Nie znaleziono folderu tej lekcji",
            C.WARNING, ms=2200)
        default = self._config.default_save_path
        if default is not None and default.exists():
            subprocess.Popen(["explorer", str(default)])

    def _on_delete(self) -> None:
        if self._deleting:                 # karta już odjeżdża — nie dubluj
            return
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
        self._deleting = True
        self.del_btn.setEnabled(False)
        anim.slide_up(self, ms=anim.FAST,
                      on_done=lambda: self.deleted.emit(self._lesson))


class HistoryPage(QWidget):
    """Lista pobranych lekcji."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        self._sort = SORTS[0]
        # Filtr wygasłych: domyślnie wyłączony, potem ostatni wybór użytkownika.
        self._hide_expired = config.hide_expired
        self._signature: Optional[tuple] = None
        self._hidden = 0
        self._intro_pending = True
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

        self.expired_btn = QPushButton(f"{I.EXPIRED}  Ukryj wygasłe", head)
        self.expired_btn.setObjectName("FilterToggle")
        self.expired_btn.setCheckable(True)
        self.expired_btn.setChecked(self._hide_expired)
        self.expired_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expired_btn.toggled.connect(self._on_toggle_expired)
        self._sync_expired_button()
        hl.addWidget(self.expired_btn)

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

    # ── nagłówek i filtr ──

    def _on_sort(self, value: str) -> None:
        self._sort = value
        self.refresh()

    def _sync_expired_button(self) -> None:
        self.expired_btn.setToolTip(
            "Lekcje z wygasłym linkiem są ukryte — kliknij, aby je pokazać."
            if self._hide_expired else
            "Ukryj lekcje, których link już wygasł (pliki zostają na dysku).")

    def _on_toggle_expired(self, checked: bool) -> None:
        self._hide_expired = checked
        self._sync_expired_button()
        self._config.hide_expired = checked
        self._config.save()
        self.refresh()

    def _set_count(self, shown: int, hidden: int) -> None:
        """Nagłówek listy: ile lekcji widać i ile schował filtr wygasłych."""
        text = f"{I.LIST}  Pobrane lekcje ({shown})"
        if hidden:
            text += f"   •   ukryto wygasłe: {hidden}"
        self.count_label.setText(text)

    # ── lista ──

    def _cards(self) -> list[LessonCard]:
        return [w for i in range(self.list_layout.count())
                if isinstance(w := self.list_layout.itemAt(i).widget(), LessonCard)]

    def _clear_rows(self) -> None:
        while self.list_layout.count() > 1:     # zostaw stretch
            it = self.list_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                # Samo `deleteLater()` zostawiłoby widget na ekranie do końca
                # bieżącej pętli zdarzeń — stara lista mignęłaby pod nową.
                w.setParent(None)
                w.deleteLater()

    def _sorted_lessons(self) -> tuple[list[dict], int]:
        lessons = load_history().get("lessons", [])
        hidden = 0
        if self._hide_expired:
            live = [x for x in lessons if not is_link_expired(x)]
            hidden = len(lessons) - len(live)
            lessons = live

        if self._sort == SORTS[0]:
            lessons.sort(key=lambda x: x.get("downloaded_at", ""), reverse=True)
        elif self._sort == SORTS[1]:
            lessons.sort(key=lambda x: x.get("downloaded_at", ""))
        elif self._sort == SORTS[2]:
            lessons.sort(key=lambda x: x.get("topic", "").lower())
        else:
            lessons.sort(key=lambda x: x.get("topic", "").lower(), reverse=True)
        return lessons, hidden

    def refresh(self) -> None:
        """Przebudowuje listę, ale tylko gdy naprawdę się zmieniła.

        Zakładka odświeża się przy każdym wejściu, a przebudowa z animacją za
        każdym razem to migotanie bez powodu — i to ono „glitchowało" przy
        kilkunastu lekcjach.
        """
        lessons, hidden = self._sorted_lessons()
        # Data wygaśnięcia zmienia kolor numeru, więc wchodzi do odcisku palca.
        signature = (self._sort, self._hide_expired, hidden, tuple(
            (x.get("url"), x.get("number"), x.get("topic"),
             x.get("downloaded_at"), is_link_expired(x)) for x in lessons))
        if signature == self._signature:
            return
        self._signature = signature
        self._hidden = hidden

        self._clear_rows()
        if not lessons:
            self._set_count(0, hidden)
            empty = label(
                f"{I.EXPIRED}\n\nWszystkie lekcje mają wygasłe linki i są ukryte.\n"
                f"Wyłącz „Ukryj wygasłe”, aby je zobaczyć."
                if hidden else
                f"{I.EMPTY}\n\nBrak pobranych lekcji.\n"
                f"Przejdź do zakładki „Pobierz”.",
                "EmptyState", wrap=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_layout.insertWidget(0, empty)
            anim.fade_in(empty, ms=anim.SLOW)
            return

        self._set_count(len(lessons), hidden)

        # Wszystkie karty wstawiamy naraz i przy wyłączonym rysowaniu: układ
        # (a z nim pasek przewijania) ustala się raz, przed jakąkolwiek animacją.
        holder = self.scroll.widget()
        holder.setUpdatesEnabled(False)
        try:
            for lesson in lessons:
                card = LessonCard(lesson, self._config)
                card.deleted.connect(self._on_card_deleted)
                self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        finally:
            holder.setUpdatesEnabled(True)

        self._play_intro()

    def _play_intro(self) -> None:
        """Kaskada wejścia — wyłącznie na przezroczystości.

        Poprzednio każda karta dojeżdżała też do swojej wysokości (`pop_in`),
        więc lista przeliczała układ kilkanaście razy w trakcie wejścia i
        skakała. Tu geometria jest gotowa od pierwszej klatki.
        """
        if not self.isVisible():
            self._intro_pending = True      # dokończymy przy pokazaniu zakładki
            return
        self._intro_pending = False
        for i, card in enumerate(self._cards()[:FADE_CAP]):
            anim.fade_in(card, ms=anim.BASE, delay=i * FADE_STEP)

    def showEvent(self, e) -> None:          # noqa: N802
        super().showEvent(e)
        if self._intro_pending:
            self._play_intro()

    def _on_card_deleted(self, lesson: dict) -> None:
        history = load_history()
        delete_lesson(history, lesson)

        # Wyjmujemy jedną kartę zamiast przebudowywać listę: pozostałe zostają
        # na swoich miejscach, a widok nie skacze na początek.
        card = self.sender()
        if isinstance(card, LessonCard):
            self.list_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._signature = None              # dane się zmieniły

        left = len(self._cards())
        if left:
            self._set_count(left, self._hidden)
        else:
            self.refresh()                  # pokaż stan pusty

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
            Toast.show_at(self.window(), f"{I.OK}  Historia wyczyszczona")
