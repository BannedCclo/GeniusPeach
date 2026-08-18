import sys
import time
import ctypes
from ctypes import wintypes

from pynput import keyboard
from PySide6.QtCore import Qt, QThread, QMetaObject
from PySide6.QtGui import QFont
# Importar QtWebEngineWidgets ANTES de instanciar a QApplication é
# obrigatório: é esse import que liga AA_ShareOpenGLContexts. Sem ele o
# painel (QWebEngineView) aborta na criação com um erro de contexto OpenGL.
from PySide6 import QtWebEngineWidgets  # noqa: F401
from PySide6.QtWidgets import QApplication

from audio_recorder import AudioRecorder
from app_state import AppState, State
from worker import Worker
import dictionary as dictionary_store
import hotkeys
import profiles as profiles_store
import settings as settings_store
from ui import theme
from ui.fonts import load_fonts
from ui.overlay import OverlayWidget
from ui.profile_toast import ProfileToast
from ui.webdashboard import WebDashboard
from ui.tray import TrayIcon

# Trava de Instância Única via Windows API
MUTEX_NAME = "Global\\GeniusPeach_SingleInstance_Mutex"
kernel32 = ctypes.windll.kernel32
mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
last_error = kernel32.GetLastError()

# ERROR_ALREADY_EXISTS = 183
if last_error == 183:
    # Se o Mutex já existir, encerra o novo processo silenciosamente
    sys.exit(0)

recorder = None
app_state = None
is_pressed = False

# ---------------------------------------------------------------------------
# start_recording/stop_recording são a lógica de verdade de "uma gravação
# está rolando", compartilhada por TRÊS gatilhos independentes: segurar o
# atalho (hold-to-talk), o duplo-clique nele (toggle) e o botão de
# microfone do painel. Nenhum duplica a checagem de estado — todos só
# fazem algo se `is_pressed`/o estado central concordarem.
# ---------------------------------------------------------------------------


def start_recording():
    global is_pressed
    # Só começa a gravar se os modelos já carregaram e não há nada em
    # andamento — evita sobrepor uma segunda gravação em cima de um
    # ditado que ainda está sendo otimizado. Devolve se começou de
    # verdade, pra quem chamou (a máquina de estado do atalho, logo
    # abaixo) saber se essa pressionada teve efeito real ou foi um no-op
    # (ex.: apertar o atalho enquanto o botão do painel já está gravando).
    ready_states = (State.IDLE, State.DONE, State.ERROR)
    if not is_pressed and app_state.state in ready_states:
        is_pressed = True
        recorder.start()
        app_state.set_state(State.LISTENING)
        return True
    return False


def stop_recording():
    global is_pressed, recording_mode
    if is_pressed:
        is_pressed = False
        recording_mode = None
        # O token da gravação que está terminando — precisa ser lido ANTES
        # de recorder.stop() (que já despacha o último trecho, se houver,
        # de forma síncrona via chunk_callback) pra viajar junto com
        # recording_finished. Worker usa esse número pra saber a quem
        # pertence cada trecho/finalização — ver app_state.py.
        token = recorder.session_token
        recorder.stop()
        app_state.recording_finished.emit(token)


# ---------------------------------------------------------------------------
# Atalho: hold-to-talk (segurar) e duplo-clique-toggle coexistem sobre a
# MESMA combinação de teclas, configurável livremente (ver hotkeys.py e a
# aba Configurações). `held_keys` é COMPARTILHADO entre este atalho e o de
# ciclar perfis logo abaixo — os dois só observam o mesmo estado físico do
# teclado, cada um checando sua própria combinação contra ele; não faz
# sentido duplicar o rastreio de "quais teclas estão fisicamente
# pressionadas agora" por atalho. `combo_down` rastreia só ESTA combinação
# (a de ditado); `recording_mode`/`last_release_time` decidem se a
# pressionada atual é um hold normal ou a metade de um duplo-clique.
# ---------------------------------------------------------------------------

current_hotkey_ids = []      # carregado das settings, atualizado por on_hotkey_changed
held_keys = set()            # ids canônicos fisicamente pressionados agora (dos DOIS atalhos)
combo_down = False           # a combinação de DITADO inteira está pressionada agora?
recording_mode = None        # None | "hold" | "toggle" — só importa enquanto is_pressed é True
last_release_time = 0.0
DOUBLE_TAP_WINDOW_S = 0.4


def _combo_fully_held(hotkey_ids):
    return bool(hotkey_ids) and all(k in held_keys for k in hotkey_ids)


def _on_hotkey_down():
    global recording_mode, last_release_time
    now = time.monotonic()
    quick_second_tap = (now - last_release_time) <= DOUBLE_TAP_WINDOW_S

    if recording_mode == "toggle":
        # Já ouvindo em modo toggle — só um duplo-clique de verdade
        # (pressionada rápida o bastante depois da última soltura)
        # desliga. Uma pressionada solta no meio do caminho é ignorada
        # (a gravação continua).
        if quick_second_tap:
            stop_recording()
        return

    if quick_second_tap:
        # 2ª pressionada rápida o bastante depois da 1ª ter soltado (que
        # já rodou como um hold curtinho, e já foi encerrada no
        # on_hotkey_up correspondente) — vira toggle de vez.
        if start_recording():
            recording_mode = "toggle"
        return

    # Pressionada comum: hold-to-talk normal.
    if start_recording():
        recording_mode = "hold"


def _on_hotkey_up():
    global last_release_time
    last_release_time = time.monotonic()
    if recording_mode == "hold":
        stop_recording()
    # "toggle" (ou None): soltar a tecla não faz nada — só o próximo
    # duplo-clique liga/desliga (ver _on_hotkey_down).


# ---------------------------------------------------------------------------
# Atalho global de CICLAR PERFIS (padrão em hotkeys.DEFAULT_CYCLE_PROFILE_HOTKEY,
# configurável na tela de Configurações — ver on_cycle_profile_hotkey_changed)
# — dispara na PRESSIONADA (borda de subida da combinação), sem hold/toggle
# nenhum, funciona com a tela do painel fechada (mesmo hook global do
# pynput do atalho de ditado, só observando outra combinação).
# ---------------------------------------------------------------------------

cycle_profile_hotkey_ids = []  # carregado das settings em main(), atualizado por on_cycle_profile_hotkey_changed
cycle_combo_down = False
current_profile_id = None    # carregado das settings, mantido em dia por on_active_profile_changed


def _on_cycle_profile_hotkey():
    global current_profile_id
    all_profiles = profiles_store.load_profiles()
    if not all_profiles:
        return
    ids = [p["id"] for p in all_profiles]
    try:
        idx = ids.index(current_profile_id)
    except ValueError:
        idx = -1  # perfil atual não existe mais (excluído por fora) — cai pro primeiro
    next_profile = all_profiles[(idx + 1) % len(all_profiles)]
    settings_store.save_settings({"profile_id": next_profile["id"]})
    app_state.profile_changed.emit(next_profile["prompt"])
    # current_profile_id só é atualizado de verdade dentro de
    # on_active_profile_changed (abaixo), que este emit também aciona —
    # mesmo canal, não importa se a troca veio daqui ou da tela de Perfis.
    app_state.active_profile_changed.emit(next_profile["id"], next_profile["name"])


def on_press(key):
    global combo_down, cycle_combo_down
    try:
        key_id = hotkeys.id_for_pynput_key(key)
        if key_id is None:
            return
        was_dictation_full = _combo_fully_held(current_hotkey_ids)
        was_cycle_full = _combo_fully_held(cycle_profile_hotkey_ids)
        held_keys.add(key_id)
        if not was_dictation_full and _combo_fully_held(current_hotkey_ids) and not combo_down:
            combo_down = True
            _on_hotkey_down()
        if not was_cycle_full and _combo_fully_held(cycle_profile_hotkey_ids) and not cycle_combo_down:
            cycle_combo_down = True
            _on_cycle_profile_hotkey()
    except AttributeError:
        pass


def on_release(key):
    global combo_down, cycle_combo_down
    try:
        key_id = hotkeys.id_for_pynput_key(key)
        if key_id is None:
            return
        was_dictation_full = _combo_fully_held(current_hotkey_ids)
        was_cycle_full = _combo_fully_held(cycle_profile_hotkey_ids)
        held_keys.discard(key_id)
        if was_dictation_full and not _combo_fully_held(current_hotkey_ids) and combo_down:
            combo_down = False
            _on_hotkey_up()
        if was_cycle_full and not _combo_fully_held(cycle_profile_hotkey_ids) and cycle_combo_down:
            cycle_combo_down = False
    except AttributeError:
        pass


# CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
CONSOLE_CLOSE_EVENTS = {0, 1, 2, 5, 6}


def _make_console_ctrl_handler(app):
    # app.exec() bloqueia a thread principal num loop nativo do Windows que
    # nunca devolve controle ao interpretador Python — por isso Ctrl+C
    # sozinho (SIGINT) não é entregue. Esse handler roda numa thread
    # separada criada pelo próprio Windows para o evento de console, e pede
    # o quit de forma thread-safe via invokeMethod.
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def handler(ctrl_type):
        if ctrl_type in CONSOLE_CLOSE_EVENTS:
            QMetaObject.invokeMethod(app, "quit", Qt.QueuedConnection)
            return True
        return False
    return handler


def main():
    global recorder, app_state, current_hotkey_ids, cycle_profile_hotkey_ids, current_profile_id

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    load_fonts()
    app.setFont(QFont(theme.FONT_FAMILY, 10))

    user_settings = settings_store.load_settings()
    current_hotkey_ids = list(user_settings["hotkey"])
    cycle_profile_hotkey_ids = list(user_settings["cycle_profile_hotkey"])
    current_profile_id = user_settings["profile_id"]
    user_profiles = profiles_store.load_profiles()
    user_dictionary = dictionary_store.load_dictionary()

    app_state = AppState()
    recorder = AudioRecorder(
        level_callback=lambda lvl: app_state.audio_level.emit(lvl),
        chunk_callback=lambda chunk, token: app_state.audio_chunk_ready.emit(chunk, token),
    )
    # Valor inicial direto, sem sinal — mesmo padrão de current_hotkey_ids
    # logo acima (o Signal input_device_changed só serve pra mudanças AO
    # VIVO vindas do Bridge depois, não pro boot).
    recorder.set_device(user_settings["input_device"])

    worker_thread = QThread()
    worker = Worker()
    worker.moveToThread(worker_thread)
    worker_thread.start()

    # worker -> estado central (a UI toda escuta só o app_state)
    worker.state_changed.connect(app_state.set_state)
    worker.raw_text_ready.connect(app_state.raw_text_ready)
    worker.optimized_text_ready.connect(app_state.optimized_text_ready)
    worker.error_occurred.connect(app_state.error_occurred)
    worker.history_entry.connect(app_state.history_entry_added)
    worker.ollama_online_changed.connect(app_state.ollama_online_changed)
    worker.models_loaded.connect(lambda: app_state.set_state(State.IDLE))
    worker.load_failed.connect(lambda msg: app_state.error_occurred.emit(f"Falha ao carregar modelos: {msg}"))

    # estado central -> worker (transcreve cada trecho ao vivo, otimiza e
    # injeta quando a gravação termina, ou recarrega os modelos quando o
    # usuário troca algo nas configurações)
    app_state.audio_chunk_ready.connect(worker.process_chunk)
    app_state.recording_finished.connect(worker.finish_session)
    app_state.reload_requested.connect(worker.load_models)
    app_state.profile_changed.connect(worker.set_active_prompt)
    app_state.dictionary_changed.connect(worker.set_dictionary_prompt)
    app_state.input_device_changed.connect(recorder.set_device)
    app_state.output_language_changed.connect(worker.set_output_language)

    def exit_app():
        app.quit()

    overlay = OverlayWidget(app_state)
    profile_toast = ProfileToast()
    dashboard = WebDashboard(
        app_state,
        whisper_model=user_settings["whisper_model"],
        ollama_model=user_settings["ollama_model"],
        hotkey_ids=user_settings["hotkey"],
        cycle_profile_hotkey_ids=user_settings["cycle_profile_hotkey"],
        device_id=user_settings["device"],
        profiles=user_profiles,
        profile_id=user_settings["profile_id"],
        dictionary=user_dictionary,
        input_device=user_settings["input_device"],
        output_language=user_settings["output_language"],
        on_exit=exit_app,
        on_start_recording=start_recording,
        on_stop_recording=stop_recording,
    )

    def open_dashboard():
        dashboard.show()
        dashboard.raise_()
        dashboard.activateWindow()

    tray = TrayIcon(
        app_state,
        on_open_dashboard=open_dashboard,
        on_exit=exit_app,
        hotkey_label=hotkeys.label_for(user_settings["hotkey"]),
    )
    tray.show()

    def on_hotkey_changed(hotkey_ids):
        global current_hotkey_ids, held_keys, combo_down, recording_mode, last_release_time
        # Se havia uma gravação em andamento (via a combinação ANTIGA),
        # encerra antes de trocar — senão ela ficaria orfã, sem nenhuma
        # tecla física capaz de soltá-la.
        if recording_mode is not None:
            stop_recording()
        current_hotkey_ids = list(hotkey_ids)
        held_keys = set()
        combo_down = False
        recording_mode = None
        last_release_time = 0.0
        tray.set_hotkey_label(hotkeys.label_for(current_hotkey_ids))
        print(f"[GeniusPeach] Atalho alterado para: {hotkeys.label_for(current_hotkey_ids)}")

    app_state.hotkey_changed.connect(on_hotkey_changed)

    def on_cycle_profile_hotkey_changed(hotkey_ids):
        global cycle_profile_hotkey_ids, held_keys, combo_down, cycle_combo_down, recording_mode, last_release_time
        # held_keys é COMPARTILHADO com o atalho de ditado (ver o
        # comentário grande onde os dois são declarados) — reset defensivo
        # igual on_hotkey_changed acima, inclusive soltando uma gravação em
        # andamento: sem isso, ela podia ficar travada sem nenhuma tecla
        # física capaz de fechá-la depois do reset de held_keys.
        if recording_mode is not None:
            stop_recording()
        cycle_profile_hotkey_ids = list(hotkey_ids)
        held_keys = set()
        combo_down = False
        cycle_combo_down = False
        recording_mode = None
        last_release_time = 0.0
        print(f"[GeniusPeach] Atalho de ciclar perfis alterado para: {hotkeys.label_for(cycle_profile_hotkey_ids)}")

    app_state.cycle_profile_hotkey_changed.connect(on_cycle_profile_hotkey_changed)

    def on_active_profile_changed(profile_id, profile_name):
        # Único handler pra QUALQUER origem da troca (atalho global de
        # ciclar OU a tela de Perfis, ver app_state.active_profile_changed)
        # — mantém current_profile_id em dia pro PRÓXIMO ciclo (senão
        # ciclar depois de trocar pela tela de Perfis recomeçaria do perfil
        # errado) e mostra o node flutuante nos dois casos.
        global current_profile_id
        current_profile_id = profile_id
        profile_toast.show_profile(profile_name)

    app_state.active_profile_changed.connect(on_active_profile_changed)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    ctrl_handler = _make_console_ctrl_handler(app)
    kernel32.SetConsoleCtrlHandler(ctrl_handler, True)

    app_state.reload_requested.emit(
        user_settings["whisper_model"], user_settings["ollama_model"], user_settings["device"]
    )
    active_profile = (
        profiles_store.find(user_profiles, user_settings["profile_id"]) or user_profiles[0]
    )
    app_state.profile_changed.emit(active_profile["prompt"])
    app_state.dictionary_changed.emit(dictionary_store.build_prompt(user_dictionary))
    app_state.output_language_changed.emit(user_settings["output_language"])

    exit_code = app.exec()

    listener.stop()
    worker_thread.quit()
    worker_thread.wait(3000)

    if mutex:
        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
