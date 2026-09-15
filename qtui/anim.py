"""
Mathloader — pomocniki animacji (Qt).

Qt rysuje z podwójnym buforowaniem (QBackingStore) i wypycha całe okno jednym
flushem, więc animacje geometrii, przezroczystości i kolorów są tu w pełni
płynne — bez rozdarć, które wymuszał Tk.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QAbstractAnimation, QByteArray, QEasingCurve, QParallelAnimationGroup,
    QPropertyAnimation, QSequentialAnimationGroup, QTimer, QVariantAnimation, Qt,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

# Standardowe czasy — spójne tempo w całej aplikacji.
FAST = 140
BASE = 220
SLOW = 340

EASE_OUT = QEasingCurve.Type.OutCubic
EASE_IN_OUT = QEasingCurve.Type.InOutCubic
EASE_BACK = QEasingCurve.Type.OutBack


def _keep(widget: QWidget, anim: QAbstractAnimation, slot: str = "_anim") -> None:
    """Trzyma referencję na animacji, żeby GC jej nie zabił w trakcie."""
    prev = getattr(widget, slot, None)
    if prev is not None:
        try:
            prev.stop()
        except RuntimeError:
            pass
    setattr(widget, slot, anim)


def stop(widget: QWidget, slot: str = "_anim") -> None:
    """Zatrzymuje trzymaną animację i zapomina o niej.

    Potrzebne np. przy zmianie motywu: `glow()` po naturalnym zakończeniu
    przemalowuje widget na kolor, który zapamiętał na starcie — czyli na kolor
    STAREJ palety. `stop()` nie emituje `finished`, więc to nie nastąpi.
    """
    anim = getattr(widget, slot, None)
    if anim is not None:
        try:
            anim.stop()
        except RuntimeError:
            pass
        setattr(widget, slot, None)


def _effect(widget: QWidget) -> QGraphicsOpacityEffect:
    eff = widget.graphicsEffect()
    if not isinstance(eff, QGraphicsOpacityEffect):
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
    return eff


# ── Przezroczystość ────────────────────────────────────────────

def fade_in(widget: QWidget, *, ms: int = BASE, delay: int = 0,
            on_done: Optional[Callable[[], None]] = None) -> None:
    """Płynne pojawienie się dowolnego widgetu.

    Po zakończeniu efekt jest zdejmowany — QGraphicsEffect trzyma osobną
    warstwę offscreen (kosztuje i psuje QWidget.grab()).
    """
    eff = _effect(widget)
    eff.setOpacity(0.0)
    widget.show()

    def _start() -> None:
        a = QPropertyAnimation(eff, QByteArray(b"opacity"), widget)
        a.setDuration(ms)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(EASE_OUT)

        def _finish() -> None:
            widget.setGraphicsEffect(None)
            if on_done:
                on_done()

        a.finished.connect(_finish)
        _keep(widget, a, "_fade_anim")
        a.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    if delay > 0:
        QTimer.singleShot(delay, _start)
    else:
        _start()


def fade_out(widget: QWidget, *, ms: int = FAST, hide: bool = True,
             on_done: Optional[Callable[[], None]] = None) -> None:
    """Płynne zniknięcie widgetu (opcjonalnie ukrywa go po zakończeniu)."""
    if not widget.isVisible():
        if on_done:
            on_done()
        return
    eff = _effect(widget)
    anim = QPropertyAnimation(eff, QByteArray(b"opacity"), widget)
    anim.setDuration(ms)
    anim.setStartValue(eff.opacity())
    anim.setEndValue(0.0)
    anim.setEasingCurve(EASE_OUT)

    def _finish() -> None:
        if hide:
            widget.hide()
        widget.setGraphicsEffect(None)
        if on_done:
            on_done()

    anim.finished.connect(_finish)
    _keep(widget, anim, "_fade_anim")
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def cross_fade(widget: QWidget, swap: Callable[[], None], *, ms: int = FAST) -> None:
    """Wygaś → podmień treść (`swap`) → rozjaśnij. Idealne do galerii."""
    def _mid() -> None:
        swap()
        fade_in(widget, ms=ms)
    fade_out(widget, ms=ms, hide=False, on_done=_mid)


# ── Wysuwanie / zwijanie (maximumHeight) ───────────────────────

def slide_down(widget: QWidget, *, ms: int = BASE,
               on_done: Optional[Callable[[], None]] = None) -> None:
    """Wysuwa widget z góry (animacja maximumHeight 0 → naturalna wysokość)."""
    widget.show()
    widget.setMaximumHeight(0)
    target = max(widget.sizeHint().height(), widget.minimumSizeHint().height())

    anim = QPropertyAnimation(widget, QByteArray(b"maximumHeight"), widget)
    anim.setDuration(ms)
    anim.setStartValue(0)
    anim.setEndValue(target)
    anim.setEasingCurve(EASE_OUT)

    def _finish() -> None:
        widget.setMaximumHeight(16777215)   # zdejmij ograniczenie
        if on_done:
            on_done()

    anim.finished.connect(_finish)
    _keep(widget, anim, "_slide_anim")
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def slide_up(widget: QWidget, *, ms: int = FAST,
             on_done: Optional[Callable[[], None]] = None) -> None:
    """Zwija widget do zera i chowa go."""
    if not widget.isVisible():
        if on_done:
            on_done()
        return
    start = widget.height()
    anim = QPropertyAnimation(widget, QByteArray(b"maximumHeight"), widget)
    anim.setDuration(ms)
    anim.setStartValue(start)
    anim.setEndValue(0)
    anim.setEasingCurve(EASE_OUT)

    def _finish() -> None:
        widget.hide()
        widget.setMaximumHeight(16777215)
        if on_done:
            on_done()

    anim.finished.connect(_finish)
    _keep(widget, anim, "_slide_anim")
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def reveal(widget: QWidget, *, ms: int = BASE) -> None:
    """Wysunięcie + rozjaśnienie równocześnie."""
    slide_down(widget, ms=ms)
    fade_in(widget, ms=ms)


# ── „Zaświecenie" (przyciągnięcie uwagi) ───────────────────────

def glow(widget: QWidget, base_color: str, *, bright: float = 0.42,
         pulses: int = 2, ms: int = 900, prop: str = "background") -> None:
    """Rozjaśnia tło widgetu i wygasza je z powrotem kilka razy (~1 s).

    Działa przez QVariantAnimation na kolorze + setStyleSheet — w Qt jest to
    przerysowanie jednego, buforowanego widgetu, więc jest gładkie.
    """
    base = QColor(base_color)
    hi = QColor(base)
    hi = hi.lighter(int(100 + bright * 100))

    group = QSequentialAnimationGroup(widget)
    half = max(60, ms // (pulses * 2))

    def _mk(c_from: QColor, c_to: QColor) -> QVariantAnimation:
        a = QVariantAnimation(widget)
        a.setDuration(half)
        a.setStartValue(c_from)
        a.setEndValue(c_to)
        a.setEasingCurve(EASE_IN_OUT)
        a.valueChanged.connect(
            lambda col: widget.setStyleSheet(
                f"#{widget.objectName()} {{ background: {QColor(col).name()};"
                f" border-radius: 10px; }}"
            )
        )
        return a

    for _ in range(pulses):
        group.addAnimation(_mk(base, hi))
        group.addAnimation(_mk(hi, base))

    group.finished.connect(
        lambda: widget.setStyleSheet(
            f"#{widget.objectName()} {{ background: {base.name()}; border-radius: 10px; }}"
        )
    )
    _keep(widget, group, "_glow_anim")
    group.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def flash_border(widget: QWidget, color: str, *, ms: int = 900, pulses: int = 3) -> None:
    """Miga obramowaniem (np. błędne pole ścieżki)."""
    group = QSequentialAnimationGroup(widget)
    half = max(60, ms // (pulses * 2))
    on = (f"#{widget.objectName()} {{ border: 2px solid {color}; "
          f"border-radius: 6px; padding: 0 9px; }}")
    off = ""

    for _ in range(pulses):
        a = QVariantAnimation(widget)
        a.setDuration(half)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.stateChanged.connect(
            lambda new, old, s=on: widget.setStyleSheet(s)
            if new == QAbstractAnimation.State.Running else None
        )
        group.addAnimation(a)
        b = QVariantAnimation(widget)
        b.setDuration(half)
        b.setStartValue(0.0)
        b.setEndValue(1.0)
        b.stateChanged.connect(
            lambda new, old, s=off: widget.setStyleSheet(s)
            if new == QAbstractAnimation.State.Running else None
        )
        group.addAnimation(b)

    group.finished.connect(lambda: widget.setStyleSheet(on))
    _keep(widget, group, "_flash_anim")
    group.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


# ── Geometria okna ─────────────────────────────────────────────

def animate_height(window: QWidget, new_h: int, *, new_y: Optional[int] = None,
                   ms: int = SLOW,
                   on_done: Optional[Callable[[], None]] = None) -> None:
    """Płynnie zmienia wysokość okna (Qt buforuje — brak rozdarć).

    `new_y` pozwala przy okazji podciągnąć okno w górę, gdy rosnąc zeszłoby
    poniżej krawędzi ekranu.
    """
    geo = window.geometry()
    end_y = geo.y() if new_y is None else new_y
    if abs(geo.height() - new_h) < 4 and end_y == geo.y():
        if on_done:
            on_done()
        return
    end = geo.__class__(geo.x(), end_y, geo.width(), new_h)

    anim = QPropertyAnimation(window, QByteArray(b"geometry"), window)
    anim.setDuration(ms)
    anim.setStartValue(geo)
    anim.setEndValue(end)
    anim.setEasingCurve(EASE_OUT)
    if on_done:
        anim.finished.connect(on_done)
    _keep(window, anim, "_geo_anim")
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def cross_fade_theme(window: QWidget, apply: Callable[[], None], *,
                     ms: int = 320) -> None:
    """Przemalowuje okno pod migawką i wygasza ją — kolory przechodzą płynnie.

    Dlaczego migawka, a nie animowanie samych wartości kolorów: każda klatka
    wymagałaby przebudowania arkusza QSS i ponownego zaaplikowania go na
    aplikacji, a Qt repolishuje wtedy wszystkie widgety naraz. Przy kilkuset
    kontrolkach przejście by szarpało. Tu jest jedno przemalowanie, a płynność
    daje zwykłe wygaszenie jednego obrazka.
    """
    ghost = QLabel(window)
    ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    ghost.setPixmap(window.grab())
    ghost.setGeometry(window.rect())

    apply()

    ghost.show()
    ghost.raise_()
    fade_out(ghost, ms=ms, hide=False, on_done=ghost.deleteLater)


def fade_in_window(window: QWidget, *, ms: int = 260) -> None:
    """Pojawienie się okna (windowOpacity — kompozytuje system)."""
    window.setWindowOpacity(0.0)
    anim = QPropertyAnimation(window, QByteArray(b"windowOpacity"), window)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(EASE_OUT)
    _keep(window, anim, "_winfade_anim")
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


# ── Kaskada ────────────────────────────────────────────────────

def stagger(items, action: Callable[[object, int], None], *,
            first: int = 0, step: int = 45, cap: int = 12) -> None:
    """Uruchamia action(item, i) z rosnącym opóźnieniem (kaskadowe wejście)."""
    for i, item in enumerate(items):
        delay = first + min(i, cap) * step
        if delay <= 0:
            action(item, i)
        else:
            QTimer.singleShot(delay, lambda it=item, ix=i: action(it, ix))


def pop_in(widget: QWidget, *, ms: int = BASE, delay: int = 0) -> None:
    """Wejście karty: rozjaśnienie + delikatne rozsunięcie w pionie."""
    widget.show()
    eff = _effect(widget)
    eff.setOpacity(0.0)
    target = max(widget.sizeHint().height(), widget.minimumSizeHint().height())
    widget.setMaximumHeight(0)

    def _start() -> None:
        grp = QParallelAnimationGroup(widget)

        a = QPropertyAnimation(eff, QByteArray(b"opacity"), widget)
        a.setDuration(ms)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(EASE_OUT)
        grp.addAnimation(a)

        b = QPropertyAnimation(widget, QByteArray(b"maximumHeight"), widget)
        b.setDuration(int(ms * 0.85))
        b.setStartValue(0)
        b.setEndValue(target)
        b.setEasingCurve(EASE_OUT)
        grp.addAnimation(b)

        def _finish() -> None:
            widget.setMaximumHeight(16777215)
            widget.setGraphicsEffect(None)

        grp.finished.connect(_finish)
        _keep(widget, grp, "_pop_anim")
        grp.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    if delay > 0:
        QTimer.singleShot(delay, _start)
    else:
        _start()
