"""Mathloader — formularz i zakładka ustawień (Qt)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from config import AppConfig, FOLDER_PLACEHOLDERS, IMAGE_PLACEHOLDERS
from downloader import (
    delete_history, get_next_lesson_number, load_history, save_history,
)
from paths import ensure_data_dir, history_file
from qtui import anim
from qtui.theme import G, I, PAD_LG, PAD_MD, PAD_SM, PAD_XL, PAD_XS
from qtui.widgets import (
    CollapsibleSection, Toast, TypeToConfirmDialog, card, glyph_label, hbox,
    hline, label, restyle, set_glyph, vbox,
)

DETAIL_TEXT = (
    "Lokalizacja zapisu lub pamięć masowa z zadeklarowaną ścieżką nie istnieje. "
    "Upewnij się, że ścieżka istnieje, a pamięć masowa jest wykrywalna przez system."
)


def reveal_in_explorer(path: Path) -> None:
    """Otwiera Eksplorator z zaznaczonym plikiem.

    Gdy pliku jeszcze nie ma (np. historia przed pierwszym pobraniem), otwiera
    sam folder danych — `/select` na nieistniejącym pliku pokazałby pusty
    Eksplorator w „Dokumentach”.
    """
    try:
        if path.exists():
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            subprocess.Popen(f'explorer "{ensure_data_dir()}"')
    except OSError:
        pass


class PathRow(QFrame):
    """Wiersz ścieżki zapisu.

    Domyślna:      [ścieżka pogrubiona] [📌 Domyślna] [wybierz] [✕ nieaktywne]
    Pozostałe:     [ścieżka]            [pinezka]     [wybierz] [✕]

    Ścieżka domyślna to ta, w której historia szuka folderu lekcji po kliknięciu
    „Otwórz". Pinezka przy dowolnym wierszu ustawia go domyślnym jednym
    kliknięciem — wiersz przeskakuje wtedy na górę listy, bo kolejność ścieżek
    jest jednocześnie kolejnością zapisu.

    Domyślnej nie da się usunąć: gdyby zniknęła, „Otwórz" nagle sięgałoby po
    inny nośnik bez żadnej decyzji użytkownika. Najpierw przypinasz inną, potem
    kasujesz tę niepotrzebną.
    """

    removed = Signal(object)
    pinned = Signal(object)              # „ustaw jako domyślną"

    def __init__(self, value: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("PathRow")
        self._is_default = False
        lay = hbox(self, m=PAD_XS, s=PAD_SM)

        self.edit = QLineEdit(value, self)
        self.edit.setObjectName(f"PathEdit{id(self)}")
        self.edit.setPlaceholderText(r"np. C:\Users\Nazwa\Lekcje")
        lay.addWidget(self.edit, 1)

        # Ikona osobno od napisu: w mieszanym tekście Qt nie podmieni fontu
        # i zamiast pinezki wyszedłby pusty prostokąt.
        self.badge = QWidget(self)
        bl = hbox(self.badge, s=PAD_XS)
        bl.addWidget(glyph_label("PIN", obj="BadgeGlyph", parent=self.badge))
        bl.addWidget(label("Domyślna", "DefaultBadge", parent=self.badge))
        self.badge.hide()
        lay.addWidget(self.badge)

        self.pin_btn = QPushButton(G.PIN, self)
        self.pin_btn.setObjectName("PinBtn")
        self.pin_btn.setFixedWidth(40)
        self.pin_btn.setMinimumHeight(38)
        self.pin_btn.setToolTip("Ustaw jako ścieżkę domyślną")
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.clicked.connect(lambda: self.pinned.emit(self))
        lay.addWidget(self.pin_btn)

        browse = QPushButton(G.BROWSE, self)
        browse.setObjectName("BrowseBtn")
        browse.setFixedWidth(46)
        browse.setMinimumHeight(38)
        browse.setToolTip("Wybierz folder…")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse)
        lay.addWidget(browse)

        self.remove_btn = QPushButton(G.CLOSE, self)
        self.remove_btn.setObjectName("IconDanger")
        self.remove_btn.setFixedWidth(40)
        self.remove_btn.setMinimumHeight(38)
        self.remove_btn.setToolTip("Usuń tę ścieżkę")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(self.remove_btn)

    @property
    def is_default(self) -> bool:
        return self._is_default

    def set_default(self, is_default: bool) -> None:
        """Podpis zamiast pinezki, pogrubiona ścieżka, zablokowane usuwanie."""
        self._is_default = is_default
        self.badge.setVisible(is_default)
        self.pin_btn.setVisible(not is_default)
        self.remove_btn.setEnabled(not is_default)
        self.remove_btn.setToolTip(
            "Ścieżki domyślnej nie można usunąć — najpierw przypnij inną"
            if is_default else "Usuń tę ścieżkę")
        # Pogrubienie idzie przez właściwość, a nie przez `setFont`: nazwa pola
        # jest już zajęta przez obramowanie błędu, a QSS i tak wygrywa z fontem.
        self.edit.setProperty("isDefault", is_default)
        restyle(self.edit)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Wybierz folder zapisu")
        if folder:
            self.edit.setText(folder.replace("/", "\\"))

    @property
    def path(self) -> str:
        return self.edit.text().strip()

    def highlight(self, color: Optional[str]) -> None:
        if color:
            self.edit.setStyleSheet(
                f"#{self.edit.objectName()} {{ border: 2px solid {color}; }}")
        else:
            self.edit.setStyleSheet("")

    def flash(self, color: str) -> None:
        anim.flash_border(self.edit, color, ms=1100, pulses=3)


class FormatField(QWidget):
    """Pole formatu z chipami placeholderów i podglądem na żywo."""

    def __init__(self, title: str, value: str, placeholders: dict,
                 preview_fn: Callable[[str], str],
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._preview_fn = preview_fn
        lay = vbox(self, s=PAD_SM)
        lay.addWidget(label(title, "FieldTitle"))

        self.edit = QLineEdit(value, self)
        self.edit.setObjectName("Mono")
        self.edit.textChanged.connect(self._update_preview)
        lay.addWidget(self.edit)

        chips = QWidget(self)
        cl = hbox(chips, s=PAD_SM)
        for ph in placeholders:
            b = QPushButton(ph, chips)
            b.setObjectName("Chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, p=ph: self._insert(p))
            cl.addWidget(b)
        cl.addStretch(1)
        lay.addWidget(chips)

        self.preview = label("", "Muted")
        lay.addWidget(self.preview)
        self._update_preview()

    def _insert(self, ph: str) -> None:
        pos = self.edit.cursorPosition()
        text = self.edit.text()
        self.edit.setText(text[:pos] + ph + text[pos:])
        self.edit.setCursorPosition(pos + len(ph))
        self.edit.setFocus()

    def _update_preview(self) -> None:
        try:
            self.preview.setText(f"Podgląd: {self._preview_fn(self.edit.text())}")
        except Exception:
            self.preview.setText("Podgląd: —")

    @property
    def value(self) -> str:
        return self.edit.text().strip()


class SettingsForm(QScrollArea):
    """Współdzielony formularz — używany przez kreator i zakładkę ustawień."""

    def __init__(self, config: AppConfig, *, offer_factory_reset: bool = False,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        self._offer_reset = offer_factory_reset
        self._rows: list[PathRow] = []

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        holder = QFrame()
        holder.setObjectName("Surface")
        self._lay = vbox(holder, m=PAD_LG, s=PAD_MD)
        self.setWidget(holder)
        self._build()

    def _build(self) -> None:
        L = self._lay

        L.addWidget(label(f"{I.FOLDER}  Foldery zapisu (kopie)", "SectionTitle"))
        L.addWidget(label(
            "Każda ścieżka = jedna kopia. Pierwsza, oznaczona jako domyślna, "
            "jest tą, w której historia szuka folderu lekcji po kliknięciu "
            "„Otwórz” — pinezką ustawisz nią dowolną inną. Trzymaj tam dysk, "
            "który zawsze jest podłączony.", "Hint", wrap=True))

        self.rows_box = QWidget()
        self.rows_layout = vbox(self.rows_box, m=PAD_XS, s=PAD_SM)
        L.addWidget(self.rows_box)

        # Kreska oddziela ścieżkę domyślną od pozostałych kopii. Marginesy dają
        # przerwę, bez której sam włos byłby w tej liście niewidoczny.
        self._sep = QWidget()
        sl = vbox(self._sep, m=PAD_SM)
        sl.addWidget(hline())
        self._sep.hide()

        add = QPushButton(f"{I.PLUS}   Dodaj folder zapisu")
        add.setObjectName("AddPath")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(lambda: self._add_row("", animate=True))
        L.addWidget(add)

        self.detail = label("", "Hint", wrap=True)
        self.detail.hide()
        L.addWidget(self.detail)

        for p in [str(p) for p in self._config.save_paths]:
            self._add_row(p)
        if not self._rows:
            self._add_row("")

        L.addSpacing(PAD_SM)
        L.addWidget(hline())
        L.addSpacing(PAD_SM)

        L.addWidget(label(f"{I.NAME_TAG}  Formaty nazewnictwa", "SectionTitle"))
        L.addWidget(label("Kliknij placeholder, aby wstawić go w formule. "
                          "Podgląd aktualizuje się na żywo.", "Hint", wrap=True))

        self.folder_fmt = FormatField(
            "Format folderu lekcji:", self._config.folder_format,
            FOLDER_PLACEHOLDERS, AppConfig.preview_folder_format)
        L.addWidget(self.folder_fmt)

        self.image_fmt = FormatField(
            "Format nazwy obrazu:", self._config.image_format,
            IMAGE_PLACEHOLDERS, AppConfig.preview_image_format)
        L.addWidget(self.image_fmt)

        L.addSpacing(PAD_SM)
        L.addWidget(hline())
        L.addSpacing(PAD_SM)

        # ── Zaawansowane (zwijane) ──
        self.advanced = CollapsibleSection(f"{I.GEAR}  Opcje zaawansowane")
        AB = self.advanced.body_layout
        AB.addWidget(label("Ręczna korekta numeru następnej lekcji, "
                           "jeśli licznik się zaciął.", "Hint", wrap=True))

        row = QWidget()
        rl = hbox(row, s=PAD_SM)
        rl.addWidget(label("Następny numer lekcji:", "FieldTitle"))
        self._initial_next = get_next_lesson_number(load_history())
        self.next_edit = QLineEdit(str(self._initial_next))
        self.next_edit.setObjectName("Small")
        self.next_edit.setFixedWidth(90)
        rl.addWidget(self.next_edit)
        rl.addStretch(1)
        AB.addWidget(row)

        # Kreator pierwszego uruchomienia nie ma jeszcze czego pokazywać —
        # pliki danych powstają dopiero przy pierwszym zapisie.
        if self._offer_reset:
            AB.addWidget(hline())
            AB.addWidget(label(f"{I.DATA}  Twoje pliki z danymi", "FieldTitle"))
            AB.addWidget(label(
                "Leżą poza folderem programu, więc aktualizacja aplikacji ich "
                "nie usuwa ani nie nadpisuje. Przycisk „Pokaż” otwiera "
                "Eksplorator z zaznaczonym plikiem.", "Hint", wrap=True))
            AB.addWidget(self._data_file_row("Ustawienia:", self._config.file))
            AB.addWidget(self._data_file_row("Historia lekcji:", history_file()))

            AB.addWidget(hline())
            AB.addWidget(label(
                "Reset do ustawień fabrycznych — usuwa całą konfigurację oraz "
                "historię i zamyka program. Wymaga wpisania słowa TAK.",
                "Hint", wrap=True))
            reset = QPushButton(f"{I.WARN}   Przywróć ustawienia fabryczne")
            reset.setObjectName("Danger")
            reset.setCursor(Qt.CursorShape.PointingHandCursor)
            reset.clicked.connect(self._factory_reset)
            AB.addWidget(reset)

        L.addWidget(self.advanced)
        L.addStretch(1)

    # ── pliki z danymi ──

    def _data_file_row(self, title: str, path: Path) -> QWidget:
        """Wiersz: [etykieta] [ścieżka do skopiowania] [Pokaż w Eksploratorze]."""
        row = QWidget()
        rl = hbox(row, s=PAD_SM)

        head = label(title, "FieldTitle")
        head.setFixedWidth(120)
        rl.addWidget(head)

        field = QLineEdit(str(path), row)
        field.setObjectName("Mono")
        field.setReadOnly(True)
        field.setToolTip(str(path))
        field.setCursorPosition(0)
        rl.addWidget(field, 1)

        show = QPushButton(f"{I.OPEN}  Pokaż", row)
        show.setObjectName("CardAction")
        show.setMinimumHeight(38)
        show.setCursor(Qt.CursorShape.PointingHandCursor)
        show.clicked.connect(lambda: reveal_in_explorer(path))
        rl.addWidget(show)
        return row

    # ── ścieżki ──

    def _add_row(self, value: str = "", *, animate: bool = False) -> None:
        row = PathRow(value)
        row.removed.connect(self._remove_row)
        row.pinned.connect(self._pin_row)
        self._rows.append(row)
        self._relayout()
        if animate:
            anim.pop_in(row, ms=anim.BASE)

    def _remove_row(self, row: PathRow) -> None:
        # Domyślnej nie ruszamy (patrz PathRow), a wiersz w trakcie znikania
        # zostaje klikalny — bez tej straży drugi klik w „✕" wywracał się na
        # `list.remove`.
        if row not in self._rows or row.is_default:
            return
        self._rows.remove(row)
        row.remove_btn.setEnabled(False)
        # Kolejność pozostałych się nie zmienia, więc układu tu NIE przestawiamy:
        # inaczej znikający wiersz podskoczyłby na koniec listy w pół animacji.
        anim.slide_up(row, ms=anim.FAST, on_done=lambda: self._drop_row(row))
        self._mark_rows()

    def _drop_row(self, row: PathRow) -> None:
        row.setParent(None)
        row.deleteLater()
        self._relayout()

    def _pin_row(self, row: PathRow) -> None:
        """Jedno kliknięcie pinezki: ta ścieżka staje się domyślna.

        Kolejność ścieżek jest zarazem kolejnością zapisu, więc przypięty wiersz
        idzie na górę — dzięki temu „domyślna" i „pierwsza" zawsze znaczą to samo.
        """
        if row not in self._rows or row.is_default:
            return
        self._rows.remove(row)
        self._rows.insert(0, row)
        self._relayout()
        self.ensureWidgetVisible(row)

    def _relayout(self) -> None:
        """Ustawia kolejność w układzie: domyślna, kreska, reszta kopii."""
        if not self._rows:
            return
        self.rows_layout.insertWidget(0, self._rows[0])
        self.rows_layout.insertWidget(1, self._sep)
        for pos, r in enumerate(self._rows[1:], start=2):
            self.rows_layout.insertWidget(pos, r)
        self._mark_rows()

    def _mark_rows(self) -> None:
        """Jedno miejsce prawdy: kto jest domyślny i co widać w wierszu."""
        for i, r in enumerate(self._rows):
            r.set_default(i == 0)
        self._sep.setVisible(len(self._rows) > 1)

    def get_paths(self) -> list[str]:
        return [r.path for r in self._rows if r.path]

    def highlight_paths(self, bad: list[str], color: Optional[str]) -> None:
        for r in self._rows:
            r.highlight(color if (color and r.path in bad) else None)

    def flash_paths(self, bad: list[str], color: str) -> None:
        for r in self._rows:
            if r.path in bad:
                r.flash(color)

    def show_detail(self, color: str) -> None:
        self.detail.setText(f"{I.WARN}  {DETAIL_TEXT}")
        self.detail.setStyleSheet(f"color: {color};")
        if not self.detail.isVisible():
            anim.reveal(self.detail, ms=anim.BASE)

    def hide_detail(self) -> None:
        if self.detail.isVisible():
            anim.slide_up(self.detail, ms=anim.FAST)

    # ── zapis / walidacja ──

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.get_paths():
            errors.append("Dodaj przynajmniej jedną ścieżkę zapisu.")
        if not self.folder_fmt.value:
            errors.append("Format folderu nie może być pusty.")
        img = self.image_fmt.value
        if not img:
            errors.append("Format obrazu nie może być pusty.")
        elif "{img}" not in img:
            errors.append("Format obrazu musi zawierać placeholder {img}.")
        return errors

    def apply_to_config(self, config: AppConfig) -> None:
        config.save_paths = self.get_paths()
        config.folder_format = self.folder_fmt.value
        config.image_format = self.image_fmt.value
        try:
            new_num = int(self.next_edit.text().strip())
            if new_num != self._initial_next:
                h = load_history()
                h["next_number"] = max(1, new_num)
                save_history(h)
                self._initial_next = h["next_number"]
        except ValueError:
            pass

    def _factory_reset(self) -> None:
        dlg = TypeToConfirmDialog(
            self.window(),
            title="Reset do ustawień fabrycznych",
            heading="Reset do ustawień fabrycznych",
            message="Zostaną trwale usunięte: cała konfiguracja oraz cała "
                    "historia lekcji. Program zamknie się, a przy kolejnym "
                    "uruchomieniu ponownie przejdziesz przez konfigurację "
                    "początkową.",
            keyword="TAK",
            confirm_text="Resetuj i zamknij",
        )
        if dlg.exec() != TypeToConfirmDialog.DialogCode.Accepted:
            return
        self._config.delete_file()
        delete_history()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()


class SettingsPage(QWidget):
    """Zakładka ustawień: formularz + belka zapisu."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        lay = vbox(self, m=PAD_LG, s=PAD_MD)

        self.form = SettingsForm(config, offer_factory_reset=True)
        lay.addWidget(self.form, 1)

        bar = QWidget(self)
        bl = hbox(bar, s=PAD_MD)
        self.status = label("", "Hint")
        bl.addWidget(self.status, 1)

        save = QPushButton("  Zapisz zmiany", bar)
        save.setObjectName("Primary")
        set_glyph(save, "CHECK")
        save.setMinimumWidth(190)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save)
        bl.addWidget(save)
        lay.addWidget(bar)

    def _save(self) -> None:
        errors = self.form.validate()
        if errors:
            self.status.setText(f"{I.WARN}  " + " • ".join(errors))
            self.status.setObjectName("Err")
            restyle(self.status)
            anim.fade_in(self.status, ms=anim.FAST)
            return
        self.form.apply_to_config(self._config)
        self._config.save()
        self.status.setText(f"{I.OK}  Zmiany zapisane pomyślnie!")
        self.status.setObjectName("Ok")
        restyle(self.status)
        anim.fade_in(self.status, ms=anim.BASE)
        Toast.show_at(self.window(), f"{I.OK}  Zapisano ustawienia")
        QTimer.singleShot(3200, lambda: anim.fade_out(
            self.status, ms=anim.BASE, hide=False,
            on_done=lambda: self.status.setText("")))
