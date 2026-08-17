import ollama
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ui import icons, theme
from ui.neumorphic import NeumorphicButton

# Movida para settings.py (o painel web também precisa dela, e não faz
# sentido um módulo de widgets ser a fonte dessa lista). Reexportada aqui
# para este módulo continuar funcionando como estava.
from settings import WHISPER_MODEL_OPTIONS  # noqa: E402


class SettingsTab(QWidget):
    """Modelo Whisper, modelo Ollama e tecla de atalho. Trocar modelo exige
    recarregar (bloqueia o ditado por alguns segundos); trocar a tecla é
    instantâneo. Quem decide o que fazer com o save é o Dashboard — esta
    aba só coleta a escolha e emite."""

    save_requested = Signal(str, str, str)  # whisper_model, ollama_model, hotkey_id

    def __init__(self, whisper_model, ollama_model, hotkey_id, hotkey_options, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(18)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft)

        self.whisper_combo = QComboBox()
        for value, label in WHISPER_MODEL_OPTIONS:
            self.whisper_combo.addItem(label, userData=value)
        self._select_by_data(self.whisper_combo, whisper_model)
        form.addRow(self._field_label("Modelo Whisper"), self.whisper_combo)

        ollama_row = QHBoxLayout()
        self.ollama_combo = QComboBox()
        self.ollama_combo.setEditable(True)
        ollama_row.addWidget(self.ollama_combo, 1)
        refresh_button = NeumorphicButton("", radius=10, margin=5)
        refresh_button.setIcon(icons.glyph_icon("refresh", theme.ON_SURFACE_VARIANT, size=17))
        refresh_button.setIconSize(QSize(17, 17))
        refresh_button.setFixedWidth(36)
        refresh_button.setToolTip("Atualizar lista de modelos instalados no Ollama")
        refresh_button.clicked.connect(lambda: self._reload_ollama_models())
        ollama_row.addWidget(refresh_button)
        form.addRow(self._field_label("Modelo Ollama"), ollama_row)

        self.hotkey_combo = QComboBox()
        for id_, label, _key in hotkey_options:
            self.hotkey_combo.addItem(label, userData=id_)
        self._select_by_data(self.hotkey_combo, hotkey_id)
        form.addRow(self._field_label("Tecla de atalho (push-to-talk)"), self.hotkey_combo)

        root.addLayout(form)

        hint = QLabel(
            "Trocar o modelo recarrega o Whisper/Ollama (alguns segundos, o ditado fica "
            "bloqueado durante a troca — o ícone da bandeja mostra \"Carregando\"). Um modelo "
            "Whisper nunca usado antes é baixado na hora, o que pode demorar bem mais."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.ON_SURFACE_VARIANT}; font-size: 11px;")
        root.addWidget(hint)

        save_row = QHBoxLayout()
        save_row.setSpacing(12)
        self.save_button = NeumorphicButton(
            "Salvar alterações", radius=10, bg=theme.PRIMARY_CONTAINER, fg=theme.ON_PRIMARY_CONTAINER
        )
        self.save_button.setIcon(icons.glyph_icon("check_circle", theme.ON_PRIMARY_CONTAINER, size=17))
        self.save_button.setIconSize(QSize(17, 17))
        self.save_button.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self.save_button)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {theme.ON_SURFACE_VARIANT}; font-size: 12px;")
        save_row.addWidget(self.status_label)
        save_row.addStretch()
        root.addLayout(save_row)

        root.addStretch()

        self._reload_ollama_models(preselect=ollama_model)

    def _field_label(self, text):
        label = QLabel(text)
        label.setStyleSheet(f"color: {theme.ON_SURFACE_VARIANT}; font-size: 12px;")
        return label

    def _select_by_data(self, combo, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        elif combo.isEditable():
            combo.setEditText(value)

    def _reload_ollama_models(self, preselect=None):
        preselect = preselect or self.ollama_combo.currentData() or self.ollama_combo.currentText()
        self.ollama_combo.clear()
        try:
            response = ollama.list()
            names = [m.model for m in response.models]
        except Exception as e:
            self.status_label.setText(f"Não foi possível listar modelos do Ollama ({e})")
            self.status_label.setStyleSheet(f"color: {theme.STATE_ERROR}; font-size: 12px;")
            if preselect:
                self.ollama_combo.addItem(preselect, userData=preselect)
            return
        for name in names:
            self.ollama_combo.addItem(name, userData=name)
        self._select_by_data(self.ollama_combo, preselect)

    def _on_save_clicked(self):
        whisper_model = self.whisper_combo.currentData()
        ollama_model = self.ollama_combo.currentData() or self.ollama_combo.currentText()
        hotkey_id = self.hotkey_combo.currentData()
        self.save_requested.emit(whisper_model, ollama_model, hotkey_id)

    def show_status(self, text, is_error=False):
        color = theme.STATE_ERROR if is_error else theme.STATE_DONE
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setText(text)
