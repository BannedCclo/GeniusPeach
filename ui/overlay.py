"""Node flutuante do GeniusPeach.

Réplica dos mockups "GeniusPeach - Node Ouvindo" e "Node Processando" do
Stitch, com as animações portadas na curva e no tempo originais:

    pulse-bar   1.0s  ease-in-out  altura 4px<->20px, opacidade 0.5<->1
                delays 0.0 0.2 0.4 0.2 0.0  (simétricos, do centro pra fora)
    dot-blink   1.4s               opacidade 0.3<->1
                delays 0.0 0.2 0.4
    ring-pulse  2.0s  easeOutCubic aro expandindo 0->15px, alpha 0.7->0

Diferença deliberada em relação ao mockup: aqui não há sombra neumórfica
(pedido explícito) — o node é chapado, com um fio de contorno só pra ter
recorte sobre janelas claras. As barras também não são puramente
decorativas como no CSS: a onda do `pulse-bar` é o envelope, e o nível real
do microfone modula a amplitude, para o medidor continuar sendo prova de
que o áudio está sendo capturado.
"""

import math

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app_state import State
from ui import brand, icons, theme

# --- constantes vindas direto do CSS do Stitch -------------------------------

BAR_COUNT = 5
BAR_WIDTH = 4          # .wave-bar { width: 4px }
BAR_GAP = 6            # gap-1.5
BAR_MIN_H = 4          # keyframe 0%
BAR_MAX_H = 20         # keyframe 50%
BAR_TRACK_H = 20       # h-5
PULSE_BAR_MS = 1000
BAR_DELAYS = (0.0, 0.2, 0.4, 0.2, 0.0)

DOT_COUNT = 3
DOT_SIZE = 8           # w-2 h-2
DOT_GAP = 6            # gap-1.5
DOT_BLINK_MS = 1400
DOT_DELAYS = (0.0, 0.2, 0.4)
DOT_MIN_OPACITY = 0.3
DOT_MAX_OPACITY = 1.0

RING_MS = 2000
RING_SPREAD = 15       # box-shadow 0 0 0 15px
RING_ALPHA = 0.7

FRAME_MS = 16          # ~60fps, para as curvas ficarem suaves


def _ease_in_out(t):
    """cubic-bezier(0.42, 0, 0.58, 1) — o `ease-in-out` do CSS."""
    return 0.5 * (1 - math.cos(math.pi * max(0.0, min(1.0, t))))


def _ease_out_cubic(t):
    """cubic-bezier(0.215, 0.61, 0.355, 1) — usado pelo ring-pulse."""
    t = max(0.0, min(1.0, t))
    return 1 - pow(1 - t, 3)


def _triangle(phase):
    """0 -> 0, 0.5 -> 1, 1 -> 0. É o formato dos keyframes do pulse-bar e do
    dot-blink, que sobem no meio e voltam."""
    return 1 - abs(phase * 2 - 1)


class WaveBars(QWidget):
    """As 5 barras do node "Ouvindo". Animação `pulse-bar` com os delays
    simétricos do mockup; a amplitude é escalada pelo nível real do
    microfone (0 = onda mínima, 1 = curso completo até 20px)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        width = BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP
        self.setFixedSize(width, BAR_TRACK_H)
        self._color = QColor(theme.PRIMARY_CONTAINER)
        self._level = 0.0
        self._smooth = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    def set_color(self, color):
        self._color = QColor(color)

    def set_level(self, level):
        self._level = max(0.0, min(1.0, level))

    def start(self):
        self._clock.restart()
        self._timer.start(FRAME_MS)

    def stop(self):
        self._timer.stop()
        self._level = 0.0
        self._smooth = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        # Suaviza o nível para o medidor não tremer a cada quadro.
        self._smooth += (self._level - self._smooth) * 0.25
        amplitude = 0.35 + 0.65 * self._smooth

        elapsed = self._clock.elapsed() if self._clock.isValid() else 0
        base = (elapsed % PULSE_BAR_MS) / PULSE_BAR_MS

        x = 0.0
        mid_y = self.height() / 2
        for i in range(BAR_COUNT):
            phase = (base + BAR_DELAYS[i]) % 1.0
            curve = _ease_in_out(_triangle(phase))

            height = BAR_MIN_H + (BAR_MAX_H - BAR_MIN_H) * curve * amplitude
            opacity = 0.5 + 0.5 * curve

            color = QColor(self._color)
            color.setAlphaF(opacity)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QRectF(x, mid_y - height / 2, BAR_WIDTH, height),
                BAR_WIDTH / 2,
                BAR_WIDTH / 2,
            )
            x += BAR_WIDTH + BAR_GAP

        painter.end()


class BlinkDots(QWidget):
    """Os 3 pontos do node "Processando". Animação `dot-blink`: opacidade
    piscando entre 0.3 e 1, com 0.2s de atraso entre eles. Note que no
    mockup os pontos NÃO sobem e descem — só a opacidade varia."""

    def __init__(self, parent=None):
        super().__init__(parent)
        width = DOT_COUNT * DOT_SIZE + (DOT_COUNT - 1) * DOT_GAP
        self.setFixedSize(width, BAR_TRACK_H)
        self._color = QColor(theme.PRIMARY_CONTAINER)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    def set_color(self, color):
        self._color = QColor(color)

    def start(self):
        self._clock.restart()
        self._timer.start(FRAME_MS)

    def stop(self):
        self._timer.stop()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        elapsed = self._clock.elapsed() if self._clock.isValid() else 0
        base = (elapsed % DOT_BLINK_MS) / DOT_BLINK_MS

        radius = DOT_SIZE / 2
        cy = self.height() / 2
        for i in range(DOT_COUNT):
            phase = (base + DOT_DELAYS[i]) % 1.0
            curve = _triangle(phase)
            opacity = DOT_MIN_OPACITY + (DOT_MAX_OPACITY - DOT_MIN_OPACITY) * curve

            color = QColor(self._color)
            color.setAlphaF(opacity)
            painter.setBrush(color)
            cx = i * (DOT_SIZE + DOT_GAP) + radius
            painter.drawEllipse(QPointF(cx, cy), radius, radius)

        painter.end()


class LogoRing(QWidget):
    """Marca do app com o aro do `.pulse-ring`. O CSS do Stitch define a
    animação mas deixa a área do logo vazia nos dois mockups — aqui ela é
    aplicada de fato, com o timing e a curva originais. Sem poço afundado:
    o node não usa sombra."""

    SIZE = 52
    MARK = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._mode = "idle"          # idle | pulse | spin
        self._color = QColor(theme.PRIMARY_CONTAINER)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def set_mode(self, mode):
        self._mode = mode
        if mode in ("pulse", "spin"):
            self._clock.restart()
            self._timer.start(FRAME_MS)
        else:
            self._timer.stop()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center = QPointF(self.SIZE / 2, self.SIZE / 2)
        elapsed = self._clock.elapsed() if self._clock.isValid() else 0

        if self._mode == "pulse":
            # ring-pulse: 0% spread 0 alpha .7 -> 70% spread 15 alpha 0 -> 100% parado
            phase = (elapsed % RING_MS) / RING_MS
            if phase <= 0.7:
                t = _ease_out_cubic(phase / 0.7)
                spread = RING_SPREAD * t
                alpha = RING_ALPHA * (1 - t)
                color = QColor(self._color)
                color.setAlphaF(alpha)
                pen = QPen(color)
                pen.setWidthF(2.5)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                radius = self.MARK / 2 + 3 + spread * 0.55
                painter.drawEllipse(center, radius, radius)
        elif self._mode == "spin":
            angle = int((elapsed / 1200.0) * 360) % 360
            pen = QPen(self._color)
            pen.setWidthF(2.5)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            arc = QRectF(3, 3, self.SIZE - 6, self.SIZE - 6)
            painter.drawArc(arc, -angle * 16, 110 * 16)

        mark_rect = QRectF(
            (self.SIZE - self.MARK) / 2, (self.SIZE - self.MARK) / 2, self.MARK, self.MARK
        )
        brand.draw_mark(painter, mark_rect)
        painter.end()


class ActionGlyph(QWidget):
    """Ícone à direita do pill (microfone / concluído / erro), em Material
    Symbols. Sem o poço extrudado da versão anterior — o node é chapado."""

    SIZE = 30

    GLYPHS = {"mic": "mic", "check": "check_circle", "alert": "warning"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._kind = "mic"
        self._color = QColor(theme.ON_SURFACE_VARIANT)

    def set_state(self, kind, color):
        self._kind = kind
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        icons.draw_glyph(
            painter, rect, self.GLYPHS.get(self._kind, "mic"), self._color, size=self.SIZE - 6
        )
        painter.end()


class FlatPill(QWidget):
    """Superfície do node: cantos totalmente arredondados (rounded-full),
    fundo chapado da paleta e um fio de contorno. Sem box-shadow."""

    def __init__(self, radius=None, parent=None):
        super().__init__(parent)
        self._radius = radius

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._radius if self._radius is not None else rect.height() / 2

        painter.setBrush(QColor(theme.SURFACE))
        pen = QPen(QColor(theme.OUTLINE_VARIANT))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()


class OverlayWidget(QWidget):
    """Node flutuante, sem moldura, sempre no topo, no canto inferior
    direito. Nunca rouba foco — WA_ShowWithoutActivating garante que o texto
    injetado continue indo pra janela que estava em uso antes do ditado."""

    STATE_LABELS = {
        State.IDLE: "Pronto",
        State.LISTENING: "Ouvindo…",
        State.TRANSCRIBING: "Transcrevendo…",
        State.OPTIMIZING: "Corrigindo texto…",
        State.DONE: "Concluído",
        State.ERROR: "Erro",
    }

    STATE_COLORS = {
        State.IDLE: theme.STATE_IDLE,
        State.LISTENING: theme.STATE_LISTENING,
        State.TRANSCRIBING: theme.STATE_TRANSCRIBING,
        State.OPTIMIZING: theme.STATE_OPTIMIZING,
        State.DONE: theme.STATE_DONE,
        State.ERROR: theme.STATE_ERROR,
    }

    WIDTH = 340
    MARGIN = 24

    def __init__(self, app_state):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.app_state = app_state
        self.setFixedWidth(self.WIDTH)

        self._build_ui()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self.setWindowOpacity(0.0)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_anim.finished.connect(self._on_anim_finished)

        app_state.state_changed.connect(self._on_state_changed)
        app_state.audio_level.connect(self.wave_bars.set_level)
        app_state.raw_text_ready.connect(self._on_raw_text)
        app_state.optimized_text_ready.connect(self._on_optimized_text)
        app_state.error_occurred.connect(self._on_error)

        self.hide()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # -- pill principal ---------------------------------------------
        # px-8 py-4 do mockup, com os cantos totalmente arredondados.
        self.pill = FlatPill()
        pill_layout = QHBoxLayout(self.pill)
        pill_layout.setContentsMargins(20, 16, 24, 16)
        pill_layout.setSpacing(14)

        self.logo_ring = LogoRing()
        pill_layout.addWidget(self.logo_ring)

        # Coluna [rótulo / indicador] — h-12 gap-2 no mockup.
        status_col = QVBoxLayout()
        status_col.setSpacing(8)
        status_col.setContentsMargins(0, 0, 0, 0)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            f"color: {theme.ON_SURFACE_VARIANT}; background: transparent;"
        )
        # text-label-md + tracking-wider + uppercase + opacity-80.
        # Qt Style Sheets não têm `letter-spacing` (seria ignorada em
        # silêncio) — o tracking só sai de verdade via QFont.
        label_font = QFont(theme.FONT_FAMILY)
        label_font.setPixelSize(14)
        label_font.setWeight(QFont.Medium)
        label_font.setLetterSpacing(QFont.AbsoluteSpacing, 0.7)  # 0.05em em 14px
        self.status_label.setFont(label_font)
        status_col.addWidget(self.status_label)

        indicator_row = QHBoxLayout()
        indicator_row.setContentsMargins(0, 0, 0, 0)
        indicator_row.setSpacing(0)
        self.wave_bars = WaveBars()
        self.wave_bars.hide()
        indicator_row.addWidget(self.wave_bars)
        self.dots = BlinkDots()
        self.dots.hide()
        indicator_row.addWidget(self.dots)
        indicator_row.addStretch()
        status_col.addLayout(indicator_row)

        pill_layout.addLayout(status_col, 1)

        self.action_glyph = ActionGlyph()
        self.action_glyph.hide()
        pill_layout.addWidget(self.action_glyph)

        root.addWidget(self.pill)

        # -- poço de texto (prévia da transcrição / erro) ----------------
        self.text_panel = FlatPill(radius=18)
        text_layout = QVBoxLayout(self.text_panel)
        text_layout.setContentsMargins(18, 14, 18, 14)
        self.text_label = QLabel("")
        self.text_label.setWordWrap(True)
        self.text_label.setMaximumHeight(84)
        self.text_label.setStyleSheet(
            f"color: {theme.ON_SURFACE_VARIANT}; font-size: 13px; background: transparent;"
        )
        text_layout.addWidget(self.text_label)
        self.text_panel.hide()
        root.addWidget(self.text_panel)

    # -- reações ao estado central ------------------------------------

    def _on_state_changed(self, state):
        if state == State.LOADING:
            return

        label = self.STATE_LABELS.get(state, "")
        color = self.STATE_COLORS.get(state, theme.STATE_IDLE)
        self.status_label.setText(label.upper())
        self.logo_ring.set_color(color)

        if state == State.LISTENING:
            self.logo_ring.set_mode("pulse")
            self.wave_bars.set_color(color)
            self.wave_bars.show()
            self.wave_bars.start()
            self.dots.stop()
            self.dots.hide()
            self.action_glyph.show()
            self.action_glyph.set_state("mic", color)
        elif state in (State.TRANSCRIBING, State.OPTIMIZING):
            self.logo_ring.set_mode("spin")
            self.wave_bars.stop()
            self.wave_bars.hide()
            self.dots.set_color(color)
            self.dots.show()
            self.dots.start()
            self.action_glyph.hide()
        elif state == State.DONE:
            self.logo_ring.set_mode("idle")
            self.wave_bars.stop()
            self.wave_bars.hide()
            self.dots.stop()
            self.dots.hide()
            self.action_glyph.show()
            self.action_glyph.set_state("check", theme.PRIMARY)
        elif state == State.ERROR:
            self.logo_ring.set_mode("idle")
            self.wave_bars.stop()
            self.wave_bars.hide()
            self.dots.stop()
            self.dots.hide()
            self.action_glyph.show()
            self.action_glyph.set_state("alert", theme.ERROR)
        else:  # IDLE
            self.logo_ring.set_mode("idle")
            self.wave_bars.stop()
            self.wave_bars.hide()
            self.dots.stop()
            self.dots.hide()
            self.action_glyph.hide()

        if state == State.LISTENING:
            self._hide_timer.stop()
            self.text_panel.hide()
            self.text_label.setText("")
            self._show()
        elif state == State.DONE:
            self._hide_timer.start(2600)
        elif state == State.ERROR:
            self._show()
            self._hide_timer.start(5000)
        elif state == State.IDLE and self.isVisible():
            self._hide_timer.start(200)

    def _on_raw_text(self, text):
        self.text_label.setStyleSheet(
            f"color: {theme.ON_SURFACE_VARIANT}; font-size: 13px; font-style: italic; background: transparent;"
        )
        self.text_label.setText(text)
        self.text_panel.show()
        self._reposition()

    def _on_optimized_text(self, text):
        self.text_label.setStyleSheet(
            f"color: {theme.ON_SURFACE}; font-size: 13px; background: transparent;"
        )
        self.text_label.setText(text)
        self.text_panel.show()
        self._reposition()

    def _on_error(self, message):
        self.text_label.setStyleSheet(
            f"color: {theme.ERROR}; font-size: 12px; background: transparent;"
        )
        self.text_label.setText(message)
        self.text_panel.show()
        self._reposition()

    # -- exibição -------------------------------------------------------

    def _reposition(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        x = screen.right() - self.width() - self.MARGIN
        y = screen.bottom() - self.height() - self.MARGIN
        self.move(x, y)

    def _show(self):
        self._reposition()
        self._hide_timer.stop()
        self._opacity_anim.stop()
        self._opacity_anim.setDuration(160)
        self._opacity_anim.setStartValue(self.windowOpacity())
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.show()
        self.raise_()
        self._opacity_anim.start()

    def _fade_out(self):
        self._opacity_anim.stop()
        self._opacity_anim.setDuration(260)
        self._opacity_anim.setStartValue(self.windowOpacity())
        self._opacity_anim.setEndValue(0.0)
        self._opacity_anim.setEasingCurve(QEasingCurve.InCubic)
        self._opacity_anim.start()

    def _on_anim_finished(self):
        if self._opacity_anim.endValue() == 0.0:
            self.hide()
