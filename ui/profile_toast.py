"""Node flutuante que mostra o nome do perfil ativo por um instante, toda
vez que ele MUDA — seja pelo atalho global de ciclar perfis (main.py,
funciona com a tela do painel fechada) ou pela própria tela de Perfis (ver
app_state.active_profile_changed, escutado nos dois lugares).

É um aviso passageiro, não um indicador de estado contínuo como o node de
gravação (ui/overlay.py) — por isso mora num arquivo à parte, mesmo
reaproveitando a superfície (`FlatPill`) e a mecânica de fade in/out de lá.
Fica no canto SUPERIOR direito de propósito (o node de gravação já ocupa o
inferior direito) — os dois podem aparecer ao mesmo tempo sem se sobrepor,
ex.: trocar de perfil bem no meio de um ditado."""

from PySide6.QtCore import QEasingCurve, QEventLoop, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from ui import theme
from ui.overlay import FlatPill


class ProfileToast(QWidget):
    MARGIN = 24
    VISIBLE_MS = 2000

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._build_ui()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self.setWindowOpacity(0.0)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_anim.finished.connect(self._on_anim_finished)

        self.hide()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.pill = FlatPill()
        pill_layout = QHBoxLayout(self.pill)
        pill_layout.setContentsMargins(20, 12, 20, 12)

        self.label = QLabel()
        font = QFont(theme.FONT_FAMILY, 11)
        font.setWeight(QFont.DemiBold)
        self.label.setFont(font)
        self.label.setStyleSheet(f"color: {theme.ON_SURFACE};")
        pill_layout.addWidget(self.label)

        root.addWidget(self.pill)

    def show_profile(self, name):
        self.label.setText(f"Perfil: {name}")
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
        self._hide_timer.start(self.VISIBLE_MS)

    def _reposition(self):
        screen = QApplication.primaryScreen().availableGeometry()
        # Mesmas duas travas do Qt que ui/overlay.py já precisa soltar — ver
        # o comentário grande lá (OverlayWidget._reposition) pro porquê.
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.setMinimumSize(0, 0)
        self.resize(self.sizeHint())
        x = screen.right() - self.width() - self.MARGIN
        y = screen.top() + self.MARGIN
        self.move(x, y)

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
