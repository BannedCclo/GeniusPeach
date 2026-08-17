# Painel do GeniusPeach renderizado por QWebEngineView, usando o HTML/CSS
# gerado no Stitch ("Peach Voice Studio") praticamente intacto.
#
# Por que webview e não widgets nativos: o design system é neumórfico, e o
# efeito depende inteiramente de `box-shadow` duplo com blur — que o Qt não
# tem. A simulação em QPainter (ui/neumorphic.py, ainda usada pelo overlay)
# empilha contornos e produz banding, não blur. Aqui o CSS roda no mesmo
# motor que gerou o mockup, então o painel é idêntico por construção.
#
# O overlay continua nativo de propósito: é janela translúcida, sem moldura,
# sempre-no-topo e que não pode roubar foco — terreno onde uma webview é
# frágil — e o medidor de áudio atualiza rápido demais para valer uma ponte.

import os
from datetime import datetime

import hotkeys
import settings as settings_store
from PySide6.QtCore import QObject, QUrl, Qt, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app_state import State
from settings import WHISPER_MODEL_OPTIONS

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# O JS espelha esses nomes em STATE_UI (ui/web/app.js).
STATE_NAMES = {
    State.LOADING: "LOADING",
    State.IDLE: "IDLE",
    State.LISTENING: "LISTENING",
    State.TRANSCRIBING: "TRANSCRIBING",
    State.OPTIMIZING: "OPTIMIZING",
    State.DONE: "DONE",
    State.ERROR: "ERROR",
}

# A ponte entrega nível de áudio no máximo a cada 80ms (~12fps). O sinal
# original chega bem mais rápido; repassar tudo só congestionaria o canal
# sem ganho visual, já que a animação das barras é CSS e roda sozinha.
LEVEL_INTERVAL_MS = 80


class Bridge(QObject):
    """Objeto exposto ao JS como `bridge`. Sinais = Python -> página;
    slots = página -> Python."""

    stateChanged = Signal(str)
    audioLevel = Signal(float)
    rawText = Signal(str)
    optimizedText = Signal(str)
    errorText = Signal(str)
    historyAdded = Signal("QVariantMap")
    ollamaStatus = Signal(bool)
    infoChanged = Signal("QVariantMap")
    statusMessage = Signal(str)

    def __init__(
        self,
        app_state,
        gpu_name,
        whisper_model,
        ollama_model,
        hotkey_ids,
        on_exit,
        on_start_recording,
        on_stop_recording,
    ):
        super().__init__()
        self.app_state = app_state
        self.gpu_name = gpu_name
        self._whisper = whisper_model
        self._ollama = ollama_model
        self._hotkey = list(hotkey_ids)  # lista de ids canônicos, ver hotkeys.py
        self._on_exit = on_exit
        self._on_start_recording = on_start_recording
        self._on_stop_recording = on_stop_recording
        self._ollama_options = [ollama_model] if ollama_model else []
        # Sem botão "Recarregar" na tela: a lista precisa vir preenchida já
        # no boot, senão o combo só teria a opção atualmente selecionada.
        self._load_ollama_models()

    # ------------------------------------------------------ Python -> página

    def info_payload(self):
        return {
            "gpu": self.gpu_name,
            "whisper": self._whisper,
            "ollama": self._ollama,
            "hotkey": list(self._hotkey),
            "hotkey_label": hotkeys.label_for(self._hotkey),
            "whisper_options": [list(o) for o in WHISPER_MODEL_OPTIONS],
            "ollama_options": list(self._ollama_options),
        }

    def push_info(self):
        self.infoChanged.emit(self.info_payload())

    # ------------------------------------------------------ página -> Python

    @Slot()
    def request_info(self):
        # Chamado quando a página termina de montar e no "Cancelar" (que
        # simplesmente redesenha os campos com os valores em vigor).
        self.push_info()
        self.stateChanged.emit(STATE_NAMES.get(self.app_state.state, "IDLE"))

    @Slot()
    def request_exit(self):
        self._on_exit()

    @Slot()
    def start_recording(self):
        # O callback aplica a mesma checagem de estado do hold-to-talk (só
        # começa se não houver nada em andamento) — um clique fora de hora
        # (app ainda carregando modelos, ou um ditado anterior em
        # transcrição) simplesmente não faz nada, em vez de travar a UI.
        self._on_start_recording()

    @Slot()
    def stop_recording(self):
        self._on_stop_recording()

    def _load_ollama_models(self):
        try:
            import ollama

            response = ollama.list()
            self._ollama_options = [m.model for m in response.models] or self._ollama_options
        except Exception:
            pass  # mantém a opção atual — a tela ainda funciona, só sem alternativas

    @Slot(str, str, "QVariantList")
    def save_settings(self, whisper_model, ollama_model, hotkey_ids):
        # hotkey_ids chega do JS como uma lista solta de ids, na ordem em
        # que o usuário apertou durante a captura — canoniza aqui (mesma
        # ordem de exibição sempre) antes de persistir.
        hotkey_ids = hotkeys.canonical_order(str(k) for k in hotkey_ids)

        settings_store.save_settings({
            "whisper_model": whisper_model,
            "ollama_model": ollama_model,
            "hotkey": hotkey_ids,
        })

        messages = ["Configurações salvas."]

        if whisper_model != self._whisper or ollama_model != self._ollama:
            self._whisper = whisper_model
            self._ollama = ollama_model
            self.app_state.reload_requested.emit(whisper_model, ollama_model)
            messages.append("Recarregando modelos…")

        if set(hotkey_ids) != set(self._hotkey):
            self._hotkey = hotkey_ids
            self.app_state.hotkey_changed.emit(hotkey_ids)
            messages.append(f"Atalho agora é {hotkeys.label_for(hotkey_ids)}.")

        self.push_info()
        self.statusMessage.emit(" ".join(messages))


class WebDashboard(QWidget):
    """Janela normal (com moldura), aberta pela bandeja. Fechar pelo X só
    esconde — quem encerra o app é o "Encerrar programa" da barra lateral,
    o "Sair" da bandeja, ou Ctrl+C. Mesma assinatura e mesmo ciclo de vida
    do painel anterior em widgets nativos."""

    def __init__(
        self,
        app_state,
        gpu_name,
        whisper_model,
        ollama_model,
        hotkey_ids,
        on_exit,
        on_start_recording,
        on_stop_recording,
    ):
        super().__init__()
        self.setWindowTitle("GeniusPeach — Painel")
        # A barra lateral come 256px fixos e os cartões do mockup têm largura
        # máxima de 900px mais a margem de 32px de cada lado — abaixo de
        # ~1300 de largura o cartão começa a ser recortado.
        self.resize(1340, 880)
        self.setMinimumSize(1120, 700)

        self.app_state = app_state
        self._last_level_ms = 0

        self.bridge = Bridge(
            app_state,
            gpu_name,
            whisper_model,
            ollama_model,
            hotkey_ids,
            on_exit,
            on_start_recording,
            on_stop_recording,
        )

        self.view = QWebEngineView(self)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.setUrl(QUrl.fromLocalFile(os.path.join(WEB_DIR, "dashboard.html")))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        app_state.state_changed.connect(self._on_state_changed)
        app_state.audio_level.connect(self._on_audio_level)
        app_state.raw_text_ready.connect(self.bridge.rawText.emit)
        app_state.optimized_text_ready.connect(self.bridge.optimizedText.emit)
        app_state.error_occurred.connect(self.bridge.errorText.emit)
        app_state.history_entry_added.connect(self._on_history_entry)
        app_state.ollama_online_changed.connect(self.bridge.ollamaStatus.emit)

    def _on_state_changed(self, state):
        self.bridge.stateChanged.emit(STATE_NAMES.get(state, "IDLE"))

    def _on_audio_level(self, level):
        # Throttle simples por relógio monotônico do Qt.
        from PySide6.QtCore import QDateTime

        now = QDateTime.currentMSecsSinceEpoch()
        if now - self._last_level_ms < LEVEL_INTERVAL_MS:
            return
        self._last_level_ms = now
        self.bridge.audioLevel.emit(float(level))

    def _on_history_entry(self, entry):
        self.bridge.historyAdded.emit({
            "time": datetime.now().strftime("%H:%M:%S"),
            "text": entry.get("optimized_text", ""),
            "transcribe": f"{entry.get('transcribe_time', 0):.2f}s",
            "optimize": f"{entry.get('optimize_time', 0):.2f}s",
        })

    def closeEvent(self, event):
        event.ignore()
        self.hide()
