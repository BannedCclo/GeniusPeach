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
    #
    # Os dois sinais carregam o TOKEN de sessão da gravação que os gerou
    # (ver AudioRecorder.session_token) — não um sinal separado de
    # "começou agora" (havia um antes; foi removido porque criava uma
    # corrida real: chegaria pela thread de main.py/pynput, enquanto os
    # trechos chegam pela thread interna do PortAudio, e o Qt não garante
    # ordem relativa entre sinais emitidos por threads diferentes. Um
    # trecho da gravação nova podia chegar ANTES do "começou", fazendo o
    # reset apagar um resultado que tinha acabado de chegar). Com o token
    # embutido em cada mensagem, o Worker decide sozinho comparando
    # números — sem depender da ordem de chegada de nada.
    audio_chunk_ready = Signal(object, int)   # np.ndarray de UM trecho, session_token
    recording_finished = Signal(int)          # session_token — hora de otimizar+injetar
    raw_text_ready = Signal(str)
    optimized_text_ready = Signal(str)
    error_occurred = Signal(str)
    history_entry_added = Signal(dict)
    ollama_online_changed = Signal(bool)
    reload_requested = Signal(str, str, str)  # whisper_model, ollama_model, device_id
    hotkey_changed = Signal(object)      # lista de ids canônicos (ver hotkeys.py)
    # Atalho global de CICLAR perfis (mesmo esquema de ids de hotkey_changed
    # acima) — troca aplica na hora, sem afetar gravação em andamento (ver
    # main.on_cycle_profile_hotkey_changed).
    cycle_profile_hotkey_changed = Signal(object)
    # Prompt do perfil ativo pra tratamento do texto — muda ao trocar de
    # perfil no ditado OU ao editar o prompt do perfil que já está ativo
    # (ver ui/webdashboard.py). Carrega o PROMPT já resolvido, não o id do
    # perfil: o Worker não precisa saber que "perfis" existem, só qual
    # texto de instrução usar no próximo finish_session — mesmo padrão de
    # reload_requested, que já manda valores concretos em vez de ids pra
    # o Worker resolver sozinho. `object` (não `str`) porque o perfil fixo
    # "Transcrição bruta" (ver profiles.RAW_PROFILE) manda `None` de
    # propósito — sinal pro Worker pular o Ollama inteiro, não um prompt.
    profile_changed = Signal(object)     # str (prompt) ou None (pula o Ollama)
    # initial_prompt já MONTADO (ver dictionary.build_prompt) pra enviesar o
    # Whisper a favor do vocabulário cadastrado no Dicionário — object (não
    # str) pelo mesmo motivo de profile_changed: dicionário vazio manda
    # None de propósito (sem viés), e um Signal(str) não aceita None.
    dictionary_changed = Signal(object)
    # Id do microfone escolhido em Configurações (ver audio_devices.py) —
    # troca aplica na próxima gravação, sem reload de modelo nenhum (ver
    # audio_recorder.AudioRecorder.set_device).
    input_device_changed = Signal(str)
    # Canal único de "qual perfil está ATIVO agora" (id, nome) — diferente
    # de profile_changed (que carrega o PROMPT, consumido só pelo Worker).
    # Os dois lados que podem trocar o perfil ativo emitem este: Bridge
    # (seleção pela tela de Perfis) e main.py (atalho global de ciclar, ver
    # DEFAULT_CYCLE_PROFILE_HOTKEY em hotkeys.py). Os dois também ESCUTAM
    # este mesmo sinal — é o que mantém o painel sincronizado quando o
    # atalho troca o perfil com a tela aberta, e o node flutuante
    # (ui/profile_toast.py) sincronizado não importa a origem da troca.
    active_profile_changed = Signal(str, str)  # profile_id, profile_name
    # Idioma de saída do texto corrigido pelo Ollama (ver config.py) — troca
    # aplica na hora, sem reload nenhum: é só um parâmetro extra passado ao
    # TextOptimizer.optimize() no próximo finish_session (ver worker.py).
    # NÃO afeta o Whisper (transcrição continua no idioma falado).
    output_language_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = State.LOADING

    def set_state(self, state):
        self.state = state
        self.state_changed.emit(state)
