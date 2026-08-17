# Qt não tem equivalente nativo ao box-shadow duplo do CSS (o que dá o
# efeito "extrudado"/"afundado" do neumorphism). `paint_surface` simula isso
# empilhando cópias do contorno arredondado com raio e opacidade
# decrescentes — uma clara (deslocada pro canto superior-esquerdo) e uma
# escura (deslocada pro inferior-direito), na mesma proporção usada no
# design gerado no Stitch (-8px/-8px branco, 8px/8px #BEBEBE).
#
# `NeumorphicPanel` e `NeumorphicButton` são os blocos usados pelo overlay e
# pelo painel pra não repetir esse cálculo em cada widget.

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QPushButton, QWidget

from ui import theme


def _rounded_path(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    return path


def paint_surface(painter, rect, radius, *, inset=False, bg=None,
                   light=None, dark=None, depth=8, layers=5):
    """Pinta uma superfície neumórfica dentro de `rect` (deixe uma margem
    de pelo menos `depth` ao redor do conteúdo real — é nela que a sombra
    "extrudada" respira; sem essa margem o Qt corta o halo no limite do
    widget)."""
    bg = QColor(bg or theme.SURFACE)
    light_base = QColor(light or theme.SHADOW_LIGHT)
    dark_base = QColor(dark or theme.SHADOW_DARK)
    rect = QRectF(rect)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    base_path = _rounded_path(rect, radius)

    if not inset:
        # Halo por fora do contorno: escuro embaixo-direita, claro em cima-
        # esquerda — como o item "flutua" sobre a superfície ao redor.
        for i in range(layers, 0, -1):
            t = i / layers
            grow = depth * t
            off = depth * 0.55 * t
            alpha = int(70 * t)

            dark = QColor(dark_base)
            dark.setAlpha(alpha)
            painter.fillPath(
                _rounded_path(rect.adjusted(-grow, -grow, grow, grow).translated(off, off), radius + grow),
                dark,
            )

            light = QColor(light_base)
            light.setAlpha(alpha)
            painter.fillPath(
                _rounded_path(rect.adjusted(-grow, -grow, grow, grow).translated(-off, -off), radius + grow),
                light,
            )

        painter.setClipPath(base_path)
        painter.fillPath(base_path, bg)
    else:
        # Poço: preenche e depois desenha as duas sombras PARA DENTRO,
        # presas ao contorno — escura em cima-esquerda, clara embaixo-
        # direita (o inverso do modo extrudado), simulando algo pressionado
        # pra dentro da superfície.
        painter.setClipPath(base_path)
        painter.fillPath(base_path, bg)

        for i in range(layers, 0, -1):
            t = i / layers
            shrink = depth * 0.5 * t
            off = depth * 0.5 * t
            alpha = int(60 * t)
            inner_radius = max(radius - shrink, 0)

            dark = QColor(dark_base)
            dark.setAlpha(alpha)
            painter.fillPath(
                _rounded_path(rect.adjusted(shrink, shrink, -shrink, -shrink).translated(-off, -off), inner_radius),
                dark,
            )

            light = QColor(light_base)
            light.setAlpha(alpha)
            painter.fillPath(
                _rounded_path(rect.adjusted(shrink, shrink, -shrink, -shrink).translated(off, off), inner_radius),
                light,
            )

    painter.restore()


class NeumorphicPanel(QWidget):
    """Container "extrudado" (ou "afundado", com `inset=True`) — coloque um
    layout normal dentro dele, mas lembre de dar margem ao próprio layout
    de pelo menos `.margin` (propriedade abaixo) pra não desenhar conteúdo
    em cima do halo da sombra. Ex.:

        panel = NeumorphicPanel(radius=20, margin=14)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(panel.margin + 10, panel.margin + 8, panel.margin + 10, panel.margin + 8)
    """

    def __init__(self, parent=None, *, radius=theme.RADIUS_LG, inset=False,
                 bg=None, margin=14, depth=8):
        super().__init__(parent)
        self.radius = radius
        self.inset = inset
        self.bg = bg or theme.SURFACE
        self.depth = depth
        self.margin = margin

    def set_inset(self, value):
        if self.inset != value:
            self.inset = value
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        m = self.margin
        rect = self.rect().adjusted(m, m, -m, -m)
        paint_surface(painter, rect, self.radius, inset=self.inset, bg=self.bg, depth=self.depth)
        painter.end()


class NeumorphicButton(QPushButton):
    """QPushButton com fundo pintado à mão — extrudado em repouso, afundado
    enquanto pressionado (o mesmo comportamento do `.neu-button:active` do
    Stitch)."""

    def __init__(self, text="", parent=None, *, radius=theme.RADIUS_MD,
                 bg=None, fg=None, bold=True, margin=6, depth=6):
        super().__init__(text, parent)
        self.radius = radius
        self.bg = bg or theme.SURFACE
        self.fg = fg or theme.ON_SURFACE
        self.margin = margin
        self.depth = depth
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        weight = 700 if bold else 500
        self.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; "
            f"color: {self.fg}; font-weight: {weight}; padding: {margin}px {margin + 10}px; }}"
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect().adjusted(self.margin, self.margin, -self.margin, -self.margin)
        paint_surface(painter, rect, self.radius, inset=self.isDown(), bg=self.bg, depth=self.depth)
        painter.end()
        super().paintEvent(event)
