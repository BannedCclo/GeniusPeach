import socket
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from app_state import State
from config import SYSTEM_PROMPT, DEFAULT_OUTPUT_LANGUAGE
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
        # Token da gravação que _session_chunks pertence agora — todo
        # trecho/finalização chega com o token de QUEM o gerou
        # (AudioRecorder.session_token); comparar números em vez de confiar
        # na ordem de chegada de sinais entre threads diferentes. Ver
        # process_chunk/finish_session.
        self._current_session_token = 0
        # Prompt do perfil ativo pra passar ao Ollama em finish_session —
        # SYSTEM_PROMPT padrão até o primeiro app_state.profile_changed
        # chegar (main.py emite um logo depois de conectar tudo, antes de
        # qualquer gravação ser possível). `None` é um valor válido e
        # DIFERENTE de "ainda não chegou": é o perfil fixo "Transcrição
        # bruta" (ver profiles.RAW_PROFILE) pedindo pra pular o Ollama de
        # propósito — ver finish_session.
        self._active_prompt = SYSTEM_PROMPT
        # Viés de vocabulário atual (ver dictionary.py) — None até o
        # primeiro app_state.dictionary_changed chegar (main.py emite um
        # logo depois de conectar tudo, igual profile_changed). Diferente
        # de _active_prompt, o CONSUMIDOR de verdade (Transcriber) é
        # recriado do zero a cada load_models — por isso guardamos aqui E
        # reaplicamos nele toda vez que ele nasce de novo, abaixo.
        self._dictionary_prompt = None
        # Idioma de saída do texto corrigido (ver app_state.output_language_changed)
        # — DEFAULT_OUTPUT_LANGUAGE até o primeiro sinal chegar, mesmo
        # padrão de _active_prompt acima (main.py emite o valor real logo
        # depois de conectar tudo, antes de qualquer gravação ser possível).
        self._output_language = DEFAULT_OUTPUT_LANGUAGE

    @Slot(object)
    def set_active_prompt(self, prompt):
        self._active_prompt = prompt

    @Slot(str)
    def set_output_language(self, language):
        self._output_language = language

    @Slot(object)
    def set_dictionary_prompt(self, prompt):
        self._dictionary_prompt = prompt
        if self.transcriber is not None:
            self.transcriber.set_initial_prompt(prompt)

    @Slot(str, str, str)
    def load_models(self, whisper_model, ollama_model, device_id):
        # Mesmo slot serve pro carregamento inicial e pra recarregar depois
        # de trocar o modelo OU o dispositivo nas configurações — solta as
        # instâncias antigas primeiro (libera a VRAM) antes de carregar as
        # novas.
        self.state_changed.emit(State.LOADING)
        self.transcriber = None
        self.optimizer = None

        try:
            self.transcriber = Transcriber(model_size=whisper_model, device_id=device_id)
            self.optimizer = TextOptimizer(model=ollama_model)
        except Exception as e:
            self.load_failed.emit(str(e))
            return

        # Reaplica o Dicionário no transcriber RECÉM-CRIADO — sem isso,
        # toda troca de modelo/GPU nas Configurações apagaria o viés de
        # vocabulário silenciosamente (o Transcriber novo nasce com
        # initial_prompt=None, sem lembrar do que o anterior tinha).
        self.transcriber.set_initial_prompt(self._dictionary_prompt)

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

    @Slot(object, int)
    def process_chunk(self, audio_data, session_token):
        """Chamado a cada pausa detectada DURANTE a gravação (ditado ao
        vivo — ver audio_recorder.py) — o estado continua LISTENING o
        tempo todo, sem flicker por trecho: o usuário pode estar
        começando a falar o próximo pedaço enquanto este termina de
        transcrever. Erro num trecho não derruba o ditado inteiro, só
        aquele pedaço é perdido."""
        if audio_data is None or len(audio_data) == 0:
            return

        if session_token > self._current_session_token:
            # Primeiro trecho de uma gravação nova — zera o acumulador
            # AQUI, na hora, comparando o token em vez de depender de um
            # sinal separado de "começou" (ver o comentário grande em
            # app_state.py sobre por que isso existia antes e foi
            # removido). Se sobrou lixo de uma gravação anterior (o
            # finish_session dela não rodou até o fim por algum motivo),
            # ele é descartado aqui, com aviso.
            if self._session_chunks:
                print(
                    f"[GeniusPeach][aviso] {len(self._session_chunks)} trecho(s) órfão(s) de "
                    f"uma gravação anterior descartados."
                )
            self._session_chunks = []
            self._session_transcribe_time = 0.0
            self._current_session_token = session_token
        elif session_token < self._current_session_token:
            # Trecho atrasado de uma gravação já superada por uma mais
            # nova — não pertence a mais nada que ainda importa.
            print("[GeniusPeach][aviso] trecho atrasado de uma gravação antiga descartado.")
            return

        if self.transcriber is None:
            # Só deveria acontecer se o usuário trocou modelo/dispositivo
            # nas Configurações bem no meio de uma gravação (o reload
            # solta o transcriber antes de recriar) — o trecho se perde,
            # mas ao menos fica visível no log em vez de silencioso.
            print("[GeniusPeach][aviso] trecho descartado: Whisper não está carregado agora.")
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

    @Slot(int)
    def finish_session(self, session_token):
        """Chamado quando a gravação termina de verdade (soltou a tecla,
        clicou o botão, ou fechou o duplo-clique de toggle) — o último
        trecho, se houve algum, já chegou por process_chunk antes disso
        (AudioRecorder.stop() despacha a cauda de forma síncrona, na MESMA
        thread que depois emite este sinal — ordem preservada entre os
        dois porque vêm da mesma origem)."""
        if session_token < self._current_session_token:
            # Sinal de término atrasado de uma gravação já superada por
            # uma mais nova (que já está sendo tratada à parte) — ignora.
            return

        if session_token > self._current_session_token:
            # Gravação sem NENHUM trecho (curta demais ou só silêncio) —
            # process_chunk nunca rodou pra ela, então o token ainda não
            # tinha avançado. Mesmo assim, descarta qualquer lixo órfão de
            # uma gravação anterior antes de seguir (senão finish_session
            # flusharia o lixo velho como se fosse o resultado desta).
            if self._session_chunks:
                print(
                    f"[GeniusPeach][aviso] {len(self._session_chunks)} trecho(s) órfão(s) de "
                    f"uma gravação anterior descartados."
                )
            self._session_chunks = []
            self._session_transcribe_time = 0.0
            self._current_session_token = session_token

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
        if self._active_prompt is None:
            # Perfil fixo "Transcrição bruta" — pula o Ollama de propósito,
            # a transcrição do Whisper É o resultado final.
            optimized_text = raw_text
        else:
            try:
                t0 = time.perf_counter()
                optimized_text = self.optimizer.optimize(
                    raw_text, system_prompt=self._active_prompt, output_language=self._output_language
                )
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
