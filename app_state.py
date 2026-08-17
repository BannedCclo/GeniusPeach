from enum import Enum, auto

from PySide6.QtCore import QObject, Signal


class State(Enum):
    LOADING = auto()
    IDLE = auto()
    LISTENING = auto()
    TRANSCRIBING = auto()
    OPTIMIZING = auto()
    DONE = auto()
    ERROR = auto()


class AppState(QObject):
    """Fonte única de verdade do estado do app — todo componente de UI
    (overlay, painel, bandeja) escuta os mesmos sinais em vez de se
    comunicar diretamente entre si."""

    state_changed = Signal(object)       # State
    audio_level = Signal(float)          # 0..1, durante LISTENING
    # Ditado ao vivo: cada trecho de áudio (delimitado por uma pausa
    # detectada durante a gravação) chega aqui pra ser transcrito na hora,
    # em vez de esperar a gravação inteira terminar. Ver worker.py.
    audio_chunk_ready = Signal(object)   # np.ndarray de UM trecho
    recording_finished = Signal()        # gravação encerrada — hora de otimizar+injetar
    raw_text_ready = Signal(str)
    optimized_text_ready = Signal(str)
    error_occurred = Signal(str)
    history_entry_added = Signal(dict)
    ollama_online_changed = Signal(bool)
    reload_requested = Signal(str, str)  # whisper_model, ollama_model
    hotkey_changed = Signal(object)      # lista de ids canônicos (ver hotkeys.py)

    def __init__(self):
        super().__init__()
        self.state = State.LOADING

    def set_state(self, state):
        self.state = state
        self.state_changed.emit(state)
