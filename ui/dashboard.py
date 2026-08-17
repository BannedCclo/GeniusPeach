from datetime import datetime

import hotkeys
import settings as settings_store
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_state import State
from ui import icons, theme
from ui.neumorphic import NeumorphicButton, NeumorphicPanel
from ui.settings_tab import SettingsTab

MAX_HISTORY = 50

STATE_LABELS = {
    State.LOADING: ("Carregando modelos…", theme.STATE_IDLE),
    State.IDLE: ("Pronto", theme.PRIMARY),
    State.LISTENING: ("Ouvindo…", theme.ON_PRIMARY_CONTAINER),
    State.TRANSCRIBING: ("Transcrevendo…", theme.ON_PRIMARY_CONTAINER),
    State.OPTIMIZING: ("Corrigindo texto…", theme.SECONDARY),
    State.DONE: ("Pronto", theme.PRIMARY),
    State.ERROR: ("Erro", theme.ERROR),
}


class Dashboard(QWidget):
    """Janela normal (com moldura), aberta pela bandeja (clique ou menu).
    Fechar pelo X só esconde — quem encerra o app de verdade é o botão
    "Encerrar programa" aqui dentro, o "Sair" da bandeja, ou Ctrl+C."""

    def __init__(self, app_state, gpu_name, whisper_model, ollama_model, hotkey_id, on_exit):
        super().__init__()
        self.setWindowTitle("GeniusPeach — Painel")
        self.resize(860, 620)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {theme.SURFACE};
                color: {theme.ON_SURFACE};
                font-family: '{theme.FONT_FAMILY}', '{theme.FONT_FAMILY_FALLBACK}';
            }}
            QTableWidget {{
                background-color: {theme.SURFACE_CONTAINER_LOWEST};
                gridline-color: {theme.SURFACE_CONTAINER_HIGH};
                border: none;
                border-radius: 10px;
            }}
            QHeaderView::section {{
                background-color: {theme.SURFACE_CONTAINER_LOW};
                color: {theme.ON_SURFACE_VARIANT};
                border: none;
                border-bottom: 1px solid {theme.SURFACE_CONTAINER_HIGH};
                padding: 8px;
                font-weight: 600;
            }}
            QTableWidget::item {{
                padding: 4px;
            }}
            QTableWidget::item:selected {{
                background-color: {theme.PRIMARY_CONTAINER};
                color: {theme.ON_PRIMARY_CONTAINER};
            }}
            QTabWidget::pane {{
                border: none;
                top: -1px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {theme.ON_SURFACE_VARIANT};
                padding: 9px 18px;
                margin-right: 4px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
            QTabBar::tab:selected {{
                background: {theme.SURFACE_CONTAINER_LOW};
                color: {theme.PRIMARY};
                font-weight: 700;
            }}
            QComboBox {{
                background-color: {theme.SURFACE_CONTAINER_LOW};
                color: {theme.ON_SURFACE};
                border: 1px solid {theme.OUTLINE_VARIANT};
                border-radius: 10px;
                padding: 7px 12px;
                min-width: 220px;
                selection-background-color: {theme.PRIMARY_CONTAINER};
            }}
            QComboBox:hover {{
                border-color: {theme.OUTLINE};
            }}
            QComboBox:focus, QComboBox:on {{
                border: 1.5px solid {theme.PRIMARY};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 26px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme.SURFACE_CONTAINER_LOWEST};
                color: {theme.ON_SURFACE};
                border: 1px solid {theme.OUTLINE_VARIANT};
                border-radius: 8px;
                padding: 4px;
                selection-background-color: {theme.PRIMARY_CONTAINER};
                selection-color: {theme.ON_PRIMARY_CONTAINER};
                outline: none;
            }}
            QPushButton {{
                background-color: {theme.SURFACE_CONTAINER_LOW};
                color: {theme.ON_SURFACE};
                border: 1px solid {theme.OUTLINE_VARIANT};
                border-radius: 10px;
                padding: 5px 8px;
            }}
            QPushButton:hover {{
                border-color: {theme.OUTLINE};
            }}
            QTableWidget::item:hover {{
                background-color: {theme.SURFACE_CONTAINER_LOW};
            }}
        """)

        self.app_state = app_state
        self._current_whisper = whisper_model
        self._current_ollama = ollama_model
        self._current_hotkey = hotkey_id

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("GeniusPeach")
        title.setStyleSheet(f"font-size: 21px; font-weight: 700; color: {theme.PRIMARY};")
        titles.addWidget(title)
        self.status_label = QLabel("Carregando…")
        self.status_label.setStyleSheet(f"color: {theme.STATE_IDLE}; font-size: 13px; font-weight: 600;")
        titles.addWidget(self.status_label)
        header.addLayout(titles)

        header.addStretch()

        exit_button = NeumorphicButton("Encerrar programa", radius=10, fg=theme.ERROR)
        exit_button.setIcon(icons.glyph_icon("power_settings_new", theme.ERROR, size=17))
        exit_button.setIconSize(QSize(17, 17))
        exit_button.clicked.connect(on_exit)
        header.addWidget(exit_button, 0, Qt.AlignTop)

        root.addLayout(header)

        tabs = QTabWidget()
        tabs.setIconSize(QSize(18, 18))
        tabs.addTab(self._build_panel_tab(gpu_name, whisper_model, ollama_model), "Painel")
        tabs.setTabIcon(0, icons.glyph_icon("mic", theme.PRIMARY, size=18))

        self.settings_tab = SettingsTab(
            whisper_model=whisper_model,
            ollama_model=ollama_model,
            hotkey_id=hotkey_id,
            hotkey_options=hotkeys.HOTKEY_OPTIONS,
        )
        self.settings_tab.save_requested.connect(self._on_save_settings)
        tabs.addTab(self.settings_tab, "Configurações")
        tabs.setTabIcon(1, icons.glyph_icon("tune", theme.ON_SURFACE_VARIANT, size=18))

        root.addWidget(tabs)

        app_state.state_changed.connect(self._on_state_changed)
        app_state.history_entry_added.connect(self._on_history_entry)
        app_state.ollama_online_changed.connect(self._on_ollama_status)

    def _build_panel_tab(self, gpu_name, whisper_model, ollama_model):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(18)

        info_card = NeumorphicPanel(radius=theme.RADIUS_LG, margin=12)
        info_layout = QVBoxLayout(info_card)
        im = info_card.margin
        info_layout.setContentsMargins(im + 12, im + 12, im + 12, im + 12)

        info = QGridLayout()
        info.setHorizontalSpacing(32)
        info.setVerticalSpacing(6)
        self._add_info_row(info, 0, "GPU", gpu_name)
        self.whisper_label = self._add_info_row(info, 1, "Modelo Whisper", whisper_model)
        self.ollama_label = self._add_info_row(info, 2, "Modelo Ollama", ollama_model)
        self.ollama_status_label = QLabel("verificando…")
        self.ollama_status_label.setStyleSheet("font-size: 12px;")
        self._add_info_row(info, 3, "Status do Ollama", None, value_widget=self.ollama_status_label)
        info_layout.addLayout(info)
        layout.addWidget(info_card)

        history_card = NeumorphicPanel(radius=theme.RADIUS_LG, margin=12, inset=True)
        history_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        history_layout = QVBoxLayout(history_card)
        hm = history_card.margin
        history_layout.setContentsMargins(hm + 12, hm + 10, hm + 12, hm + 12)
        history_layout.setSpacing(10)

        history_header = QHBoxLayout()
        history_header.setSpacing(8)
        history_icon = QLabel()
        history_icon.setPixmap(icons.glyph_icon("history", theme.PRIMARY, size=16, box=18).pixmap(18, 18))
        history_header.addWidget(history_icon)
        history_label = QLabel("Histórico de ditados")
        history_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {theme.ON_SURFACE};")
        history_header.addWidget(history_label)
        history_header.addStretch()
        history_layout.addLayout(history_header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Hora", "Texto", "Transcrição", "Otimização"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        history_layout.addWidget(self.table, 1)

        layout.addWidget(history_card, 1)

        return panel

    def _add_info_row(self, grid, row, label, value, value_widget=None):
        l = QLabel(label)
        l.setStyleSheet(f"color: {theme.ON_SURFACE_VARIANT}; font-size: 12px;")
        grid.addWidget(l, row, 0)
        if value_widget is not None:
            grid.addWidget(value_widget, row, 1)
            return value_widget
        v = QLabel(value)
        v.setStyleSheet(f"font-size: 12px; color: {theme.ON_SURFACE};")
        grid.addWidget(v, row, 1)
        return v

    def _on_save_settings(self, whisper_model, ollama_model, hotkey_id):
        settings_store.save_settings({
            "whisper_model": whisper_model,
            "ollama_model": ollama_model,
            "hotkey": hotkey_id,
        })

        messages = ["Configurações salvas."]

        models_changed = whisper_model != self._current_whisper or ollama_model != self._current_ollama
        if models_changed:
            self._current_whisper = whisper_model
            self._current_ollama = ollama_model
            self.whisper_label.setText(whisper_model)
            self.ollama_label.setText(ollama_model)
            self.app_state.reload_requested.emit(whisper_model, ollama_model)
            messages.append("recarregando modelos…")

        if hotkey_id != self._current_hotkey:
            self._current_hotkey = hotkey_id
            self.app_state.hotkey_changed.emit(hotkey_id)
            messages.append(f"atalho agora é {hotkeys.label_for(hotkey_id)}.")

        self.settings_tab.show_status(" ".join(messages))

    def _on_state_changed(self, state):
        text, color = STATE_LABELS.get(state, ("", theme.STATE_IDLE))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600;")

    def _on_history_entry(self, entry):
        self.table.insertRow(0)
        self.table.setItem(0, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        self.table.setItem(0, 1, QTableWidgetItem(entry["optimized_text"]))
        self.table.setItem(0, 2, QTableWidgetItem(f"{entry['transcribe_time']:.2f}s"))
        self.table.setItem(0, 3, QTableWidgetItem(f"{entry['optimize_time']:.2f}s"))
        while self.table.rowCount() > MAX_HISTORY:
            self.table.removeRow(self.table.rowCount() - 1)

    def _on_ollama_status(self, online):
        if online:
            self.ollama_status_label.setText("● online")
            self.ollama_status_label.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 12px;")
        else:
            self.ollama_status_label.setText("● offline")
            self.ollama_status_label.setStyleSheet(f"color: {theme.ERROR}; font-size: 12px;")

    def closeEvent(self, event):
        event.ignore()
        self.hide()
