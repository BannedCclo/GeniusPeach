# Ícones via Material Symbols Outlined (a mesma fonte que o Stitch usa nas
# telas geradas) em vez de vetor desenhado à mão — glifos ficam disponíveis
# por nome de ligadura (ex. "mic", "check_circle", "warning", "refresh").
# Precisa de `ui.fonts.load_fonts()` já ter rodado.

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

FONT_FAMILY = "Material Symbols Outlined"


def icon_font(pixel_size):
    font = QFont(FONT_FAMILY)
    font.setPixelSize(pixel_size)
    return font


def draw_glyph(painter, rect, glyph, color, size=None):
    """Desenha um glifo centralizado em `rect` (QRect/QRectF)."""
    rect = QRectF(rect)
    px = size or max(10, int(min(rect.width(), rect.height()) * 0.62))
    painter.save()
    painter.setFont(icon_font(px))
    painter.setPen(QColor(color))
    painter.drawText(rect, Qt.AlignCenter, glyph)
    painter.restore()


def glyph_icon(glyph, color, size=22, box=None):
    """Renderiza um glifo pra um QIcon (uso em QPushButton.setIcon(),
    QTabWidget.setTabIcon(), etc.)."""
    box = box or size + 10
    pixmap = QPixmap(box, box)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    draw_glyph(painter, pixmap.rect(), glyph, color, size)
    painter.end()
    return QIcon(pixmap)
