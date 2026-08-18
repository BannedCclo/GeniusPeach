"""Node flutuante do GeniusPeach.

Réplica dos mockups "GeniusPeach - Node Ouvindo" e "Node Processando" do
Stitch, com as animações portadas na curva e no tempo originais:

    dot-blink   1.4s               opacidade 0.3<->1
                delays 0.0 0.2 0.4
    ring-pulse  2.0s  easeOutCubic aro expandindo 0->15px, alpha 0.7->0

As barras do node "Ouvindo" (`WaveBars`) NÃO seguem a animação `pulse-bar`
do mockup — em vez de uma curva decorativa com atraso escalonado por barra,
funcionam como um espectro de áudio: todas respondem ao MESMO nível atual
do microfone (não é uma forma de onda viajando de um lado pro outro), com
um peso fixo por barra pra parecer um espectro de verdade em vez de um
bloco uniforme (ver a classe mais abaixo).

Diferença deliberada em relação ao mockup: aqui não há sombra neumórfica
(pedido explícito) — o node é chapado, com um fio de contorno só pra ter
recorte sobre janelas claras.
"""

import random

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QEventLoop,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

from app_state import State
from ui import icons, theme

# Cor única de tudo que aparece no node (barras, pontos, ícones de
# check/alerta) — pedido do usuário: nada de cor por estado, um tom só,
# escuro o bastante pra contrastar com o fundo quase branco do pill
# (theme.SURFACE). Mesmo âmbar escuro já usado noutros lugares do app pro
# estado "concluído" — contraste bom sem sair da família de cor da marca.
ICON_COLOR = theme.PRIMARY

# --- constantes vindas direto do CSS do Stitch -------------------------------

BAR_COUNT = 5
BAR_WIDTH = 4          # .wave-bar { width: 4px }
BAR_GAP = 6            # gap-1.5
BAR_MIN_H = 4          # keyframe 0%
BAR_MAX_H = 20         # keyframe 50%
BAR_TRACK_H = 20       # h-5

# Pesos fixos por barra — perfil "montanha", a do meio mais alta, as das
# pontas mais baixas — pra a mesma leitura de nível parecer um espectro de
# áudio (várias barras de tamanhos diferentes) em vez de um bloco uniforme
# subindo e descendo junto.
WAVE_BAR_WEIGHTS = (0.55, 0.8, 1.0, 0.8, 0.55)
# Tremor aleatório por amostra — sem isso, com o mesmo nível sustentado
# todas as barras cresceriam junto na mesma proporção, parecendo um bloco
# "respirando" em vez de um espectro vivo com cada barra oscilando um
# pouco por conta própria.
WAVE_JITTER = 0.3  # +-30%
# Ballistics de VU-meter: sobe rápido (o pico da voz fica visível), desce
# devagar (rastro suave) — é o que faz o medidor parecer "de espectro" em
# vez de só acender e apagar junto com cada amostra. 2ª rodada: mais
# ágeis que antes (attack 0.5->0.65, decay 0.12->0.2), a pedido do
# usuário — a 1ª rodada pareceu pouco animada na prática.
WAVE_ATTACK = 0.65
WAVE_DECAY = 0.2

DOT_COUNT = 3
DOT_SIZE = 8           # w-2 h-2
DOT_GAP = 6            # gap-1.5
DOT_BLINK_MS = 1400
DOT_DELAYS = (0.0, 0.2, 0.4)
DOT_MIN_OPACITY = 0.3
DOT_MAX_OPACITY = 1.0

FRAME_MS = 16          # ~60fps, para as curvas ficarem suaves


def _triangle(phase):
    """0 -> 0, 0.5 -> 1, 1 -> 0. É o formato dos keyframes do pulse-bar e do
    dot-blink, que sobem no meio e voltam."""
    return 1 - abs(phase * 2 - 1)


class WaveBars(QWidget):
    """As 5 barras do node "Ouvindo" — espectro de áudio: TODAS respondem
    ao mesmo nível atual do microfone (`set_level`), cada uma com um peso
    fixo (`WAVE_BAR_WEIGHTS`) e um tremor leve, pra ler como várias barras
    de espectro em vez de um bloco uniforme. Sobe rápido/desce devagar
    (`WAVE_ATTACK`/`WAVE_DECAY`) só suaviza a transição ENTRE as amostras
    reais que chegam a cada `config.AUDIO_LEVEL_INTERVAL_MS` — não inventa
    movimento por conta própria quando não há áudio novo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        width = BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP
        self.setFixedSize(width, BAR_TRACK_H)
        self._color = QColor(ICON_COLOR)
        self._current = [0.0] * BAR_COUNT
        self._target = [0.0] * BAR_COUNT
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_color(self, color):
        self._color = QColor(color)

    def set_level(self, level):
        level = max(0.0, min(1.0, level))
        for i in range(BAR_COUNT):
            jitter = (1 - WAVE_JITTER) + (2 * WAVE_JITTER) * random.random()
            self._target[i] = min(1.0, level * WAVE_BAR_WEIGHTS[i] * jitter)

    def start(self):
        self._current = [0.0] * BAR_COUNT
        self._target = [0.0] * BAR_COUNT
        self._timer.start(FRAME_MS)

    def stop(self):
        self._timer.stop()
        self._current = [0.0] * BAR_COUNT
        self._target = [0.0] * BAR_COUNT
        self.update()

    def _tick(self):
        moved = False
        for i in range(BAR_COUNT):
            rate = WAVE_ATTACK if self._target[i] > self._current[i] else WAVE_DECAY
            delta = (self._target[i] - self._current[i]) * rate
            if abs(delta) > 0.001:
                moved = True
            self._current[i] += delta
        if moved:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        x = 0.0
        mid_y = self.height() / 2
        for level in self._current:
            height = BAR_MIN_H + (BAR_MAX_H - BAR_MIN_H) * level
            opacity = 0.5 + 0.5 * level

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
        self._color = QColor(ICON_COLOR)
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


class StatusGlyph(QWidget):
    """Ícone de conclusão/erro que substitui a animação quando o pill
    "compacta" ao terminar (DONE) ou falhar (ERROR). Mesma altura fixa das
    animações (BAR_TRACK_H) — troca de conteúdo dentro do pill nunca muda
    sua altura, só a largura."""

    GLYPHS = {"check": "check_circle", "alert": "warning"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(BAR_TRACK_H, BAR_TRACK_H)
        self._kind = "check"

    def set_state(self, kind):
        self._kind = kind
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        icons.draw_glyph(
            painter, rect, self.GLYPHS.get(self._kind, "check"), ICON_COLOR, size=BAR_TRACK_H - 2
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

    MARGIN = 24

    def __init__(self, app_state):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.app_state = app_state

        self._build_ui()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self.setWindowOpacity(0.0)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_anim.finished.connect(self._on_anim_finished)

        app_state.state_changed.connect(self._on_state_changed)
        app_state.audio_level.connect(self.wave_bars.set_level)

        self.hide()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # -- pill principal ---------------------------------------------
        # Sem texto nenhum (removido a pedido do usuário) — só a animação
        # (barras/pontos) ou, quando concluído/erro, um ícone fixo. Altura
        # do preenchimento vertical é só o suficiente pra a onda de som
        # (que já ocupa a altura cheia de BAR_TRACK_H no pico) não encostar
        # na borda arredondada do pill — por isso bem menor que o padding
        # generoso de antes.
        self.pill = FlatPill()
        pill_layout = QHBoxLayout(self.pill)
        pill_layout.setContentsMargins(14, 4, 14, 4)
        pill_layout.setSpacing(0)

        self.wave_bars = WaveBars()
        self.wave_bars.hide()
        pill_layout.addWidget(self.wave_bars)

        self.dots = BlinkDots()
        self.dots.hide()
        pill_layout.addWidget(self.dots)

        self.status_glyph = StatusGlyph()
        self.status_glyph.hide()
        pill_layout.addWidget(self.status_glyph)

        root.addWidget(self.pill)

    # -- reações ao estado central ------------------------------------

    def _on_state_changed(self, state):
        if state == State.LOADING:
            return

        if state == State.LISTENING:
            self.wave_bars.show()
            self.wave_bars.start()
            self.dots.stop()
            self.dots.hide()
            self.status_glyph.hide()
        elif state in (State.TRANSCRIBING, State.OPTIMIZING):
            self.wave_bars.stop()
            self.wave_bars.hide()
            self.dots.show()
            self.dots.start()
            self.status_glyph.hide()
        elif state == State.DONE:
            # Pill "compacta": nada de animação, só o ícone de check —
            # encolhe sozinho pro tamanho mínimo (ver _reposition).
            self.wave_bars.stop()
            self.wave_bars.hide()
            self.dots.stop()
            self.dots.hide()
            self.status_glyph.set_state("check")
            self.status_glyph.show()
        elif state == State.ERROR:
            self.wave_bars.stop()
            self.wave_bars.hide()
            self.dots.stop()
            self.dots.hide()
            self.status_glyph.set_state("alert")
            self.status_glyph.show()
        else:  # IDLE — nada visível, pill vazio prestes a sumir
            self.wave_bars.stop()
            self.wave_bars.hide()
            self.dots.stop()
            self.dots.hide()
            self.status_glyph.hide()

        if state == State.LISTENING:
            self._hide_timer.stop()
            self._show()
        elif state == State.DONE:
            self._hide_timer.start(2600)
        elif state == State.ERROR:
            self._show()
            self._hide_timer.start(5000)
        elif state == State.IDLE and self.isVisible():
            self._hide_timer.start(200)

        # Cobre os estados que não passam por _show() (TRANSCRIBING/
        # OPTIMIZING/DONE) — sem isto, o node só re-ajustava o tamanho em
        # LISTENING/ERROR, deixando o pill grande (com animação) mesmo
        # depois de trocar pro ícone de check bem menor.
        if self.isVisible():
            self._reposition()

    # -- exibição -------------------------------------------------------

    def _reposition(self):
        screen = QApplication.primaryScreen().availableGeometry()
        # Duas travas do Qt que impedem o node de encolher de volta ao
        # trocar pra um conteúdo menor (ex.: pontos animados -> ícone de
        # check), mesmo os widgets filhos já estando certos na hora:
        # (1) o layout só recalcula o tamanho de verdade
        # quando processa o evento de LayoutRequest pendente — sem isso,
        # sizeHint() abaixo devolve o valor de ANTES da troca; só processa
        # eventos de layout/pintura, não entrada do usuário, pra não
        # arriscar reentrância com cliques/teclado no meio de um sinal do
        # app_state. (2) minimumSize() fica travado na MAIOR medida que a
        # janela já teve — setMinimumSize(0, 0) solta esse piso antes do
        # resize.
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.setMinimumSize(0, 0)
        self.resize(self.sizeHint())
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
