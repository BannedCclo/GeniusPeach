from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app_state import State
from ui import brand, theme

# IDLE/DONE não entram aqui — o texto deles depende da tecla de atalho
# configurada, montado dinamicamente em _label_for_state.
STATE_LABELS = {
    State.LOADING: "Carregando modelos…",
    State.LISTENING: "Ouvindo…",
    State.TRANSCRIBING: "Transcrevendo…",
    State.OPTIMIZING: "Processando…",
    State.ERROR: "Erro — veja o painel",
}

STATE_COLORS = {
    State.LOADING: theme.STATE_IDLE,
    State.IDLE: theme.STATE_DONE,
    State.LISTENING: theme.STATE_LISTENING,
    State.TRANSCRIBING: theme.STATE_TRANSCRIBING,
    State.OPTIMIZING: theme.STATE_OPTIMIZING,
    State.DONE: theme.STATE_DONE,
    State.ERROR: theme.STATE_ERROR,
}


def _draw_icon(status_color):
    """Pêssego + folha (design original do app) com um aro colorido no
    canto indicando o estado atual — dá pra saber se está ativo/ouvindo/
    processando sem nem abrir o painel."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    brand.draw_mark(painter, QRect(0, 0, 64, 64), ring_color=status_color, ring_bg=theme.ON_SURFACE)
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, app_state, on_open_dashboard, on_exit, hotkey_label, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._on_open_dashboard = on_open_dashboard
        self.hotkey_label = hotkey_label

        self.setIcon(_draw_icon(theme.STATE_IDLE))
        self.setToolTip("GeniusPeach — carregando…")

        menu = QMenu()
        self.status_action = QAction(STATE_LABELS[State.LOADING])
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()

        open_action = QAction("Abrir painel")
        open_action.triggered.connect(on_open_dashboard)
        menu.addAction(open_action)

        menu.addSeparator()
        exit_action = QAction("Sair")
        exit_action.triggered.connect(on_exit)
        menu.addAction(exit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

        app_state.state_changed.connect(self._on_state_changed)

    def set_hotkey_label(self, label):
        self.hotkey_label = label
        self._on_state_changed(self.app_state.state)

    def _on_activated(self, reason):
        # Trigger = clique único, o jeito como o Windows ativa um ícone a
        # partir do menu de ícones ocultos (a setinha "^" da bandeja) — não
        # dá pra depender de duplo-clique lá. Mantém DoubleClick também
        # pelo comportamento padrão de ícone fixado direto na bandeja.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._on_open_dashboard()

    def _label_for_state(self, state):
        if state in (State.IDLE, State.DONE):
            return f"Pronto — segure {self.hotkey_label} para ditar"
        return STATE_LABELS.get(state, "GeniusPeach")

    def _on_state_changed(self, state):
        label = self._label_for_state(state)
        color = STATE_COLORS.get(state, theme.STATE_IDLE)
        self.setIcon(_draw_icon(color))
        self.setToolTip(f"GeniusPeach — {label}")
        self.status_action.setText(label)
