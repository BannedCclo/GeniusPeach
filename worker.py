import socket
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from app_state import State
from injector import inject_text
from text_optimizer import TextOptimizer
from transcriber import Transcriber

OLLAMA_HEALTHCHECK_HOST = "127.0.0.1"
OLLAMA_HEALTHCHECK_PORT = 11434
OLLAMA_HEALTHCHECK_INTERVAL_MS = 8000


class Worker(QObject):
    """Roda numa QThread própria: carregamento dos modelos e o pipeline
    completo de transcrição/otimização/injeção. Mantém isso fora da thread
    do hook de teclado (pynput) e fora da thread da UI (Qt)."""

    models_loaded = Signal()
    load_failed = Signal(str)
    state_changed = Signal(object)          # State
    raw_text_ready = Signal(str)
    optimized_text_ready = Signal(str)
    error_occurred = Signal(str)
    history_entry = Signal(dict)
    ollama_online_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.transcriber = None
        self.optimizer = None
        self._health_timer = None
        # Texto (raw) de cada trecho já transcrito da gravação em
        # andamento, mais o tempo total gasto transcrevendo — usado só na
        # virada de finish_session, depois zerados pra próxima gravação.
        self._session_chunks = []
        self._session_transcribe_time = 0.0

    @Slot(str, str)
    def load_models(self, whisper_model, ollama_model):
        # Mesmo slot serve pro carregamento inicial e pra recarregar depois
        # de trocar o modelo nas configurações — solta as instâncias antigas
        # primeiro (libera a VRAM) antes de carregar as novas.
        self.state_changed.emit(State.LOADING)
        self.transcriber = None
        self.optimizer = None

        try:
            self.transcriber = Transcriber(model_size=whisper_model)
            self.optimizer = TextOptimizer(model=ollama_model)
        except Exception as e:
            self.load_failed.emit(str(e))
            return

        self.models_loaded.emit()
        if self._health_timer is None:
            self._start_health_check()

    def _start_health_check(self):
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_ollama)
        self._health_timer.start(OLLAMA_HEALTHCHECK_INTERVAL_MS)
        self._check_ollama()

    def _check_ollama(self):
        try:
            with socket.create_connection(
                (OLLAMA_HEALTHCHECK_HOST, OLLAMA_HEALTHCHECK_PORT), timeout=0.5
            ):
                online = True
        except OSError:
            online = False
        self.ollama_online_changed.emit(online)

    @Slot(object)
    def process_chunk(self, audio_data):
        """Chamado a cada pausa detectada DURANTE a gravação (ditado ao
        vivo — ver audio_recorder.py) — o estado continua LISTENING o
        tempo todo, sem flicker por trecho: o usuário pode estar
        começando a falar o próximo pedaço enquanto este termina de
        transcrever. Erro num trecho não derruba o ditado inteiro, só
        aquele pedaço é perdido."""
        if self.transcriber is None or audio_data is None or len(audio_data) == 0:
            return

        try:
            t0 = time.perf_counter()
            text = self.transcriber.transcribe(audio_data)
            self._session_transcribe_time += time.perf_counter() - t0
        except Exception as e:
            self.error_occurred.emit(f"Erro ao transcrever um trecho: {e}")
            return

        if not text:
            return

        self._session_chunks.append(text)
        self.raw_text_ready.emit(" ".join(self._session_chunks))

    @Slot()
    def finish_session(self):
        """Chamado quando a gravação termina de verdade (soltou a tecla,
        clicou o botão, ou fechou o duplo-clique de toggle) — o último
        trecho já chegou por process_chunk antes disso: AudioRecorder.stop()
        despacha a cauda de forma síncrona, e sinais Qt entre as mesmas
        duas threads preservam a ordem de chegada."""
        chunks = self._session_chunks
        transcribe_time = self._session_transcribe_time
        self._session_chunks = []
        self._session_transcribe_time = 0.0

        if not chunks:
            self.state_changed.emit(State.IDLE)
            return

        raw_text = " ".join(chunks)
        self.state_changed.emit(State.OPTIMIZING)

        optimize_time = 0.0
        try:
            t0 = time.perf_counter()
            optimized_text = self.optimizer.optimize(raw_text)
            optimize_time = time.perf_counter() - t0
        except Exception as e:
            # Ollama fora do ar não pode significar perder o ditado — cai
            # pro texto cru do Whisper em vez de travar tudo.
            self.error_occurred.emit(f"Ollama indisponível, usando texto sem correção: {e}")
            optimized_text = raw_text

        self.optimized_text_ready.emit(optimized_text)
        inject_text(optimized_text)

        total_elapsed = transcribe_time + optimize_time
        print(
            f"[GeniusPeach] Transcrição ao vivo: {transcribe_time:.2f}s (soma dos trechos) "
            f"| Otimização: {optimize_time:.2f}s"
        )

        self.history_entry.emit({
            "raw_text": raw_text,
            "optimized_text": optimized_text,
            "transcribe_time": transcribe_time,
            "optimize_time": optimize_time,
            "total_time": total_elapsed,
        })
        self.state_changed.emit(State.DONE)
