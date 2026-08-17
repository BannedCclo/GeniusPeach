# Marca própria do GeniusPeach — pêssego + folha, desenhada via QPainter.
# Deliberadamente NÃO é o logo gerado no Stitch (aquele ainda não deve ser
# usado); é o mesmo vetor que já existia no ícone da bandeja, reaproveitado
# aqui pra também aparecer no node flutuante.

from PySide6.QtGui import QColor

PEACH = QColor(255, 140, 105)
LEAF = QColor(46, 139, 87)


def draw_mark(painter, rect, ring_color=None, ring_bg=None):
    """Desenha o pêssego+folha dentro de `rect` (QRect/QRectF quadrado).
    Se `ring_color` for passado, desenha também o aro de status no canto
    inferior-direito (como no ícone da bandeja)."""
    from PySide6.QtCore import Qt

    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    s = min(w, h) / 64.0  # escala em cima do desenho original, feito pra 64x64

    painter.save()
    painter.translate(x, y)
    painter.scale(s, s)
    painter.setPen(Qt.NoPen)

    painter.setBrush(PEACH)
    painter.drawEllipse(6, 6, 52, 52)

    painter.setBrush(LEAF)
    painter.drawEllipse(30, 2, 16, 16)

    if ring_color is not None:
        painter.setBrush(QColor(ring_color))
        if ring_bg is not None:
            painter.setPen(QColor(ring_bg))
        painter.drawEllipse(38, 38, 22, 22)

    painter.restore()
