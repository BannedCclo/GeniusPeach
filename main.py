import sys
import time
import ctypes
from ctypes import wintypes

import torch
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
import hotkeys
import settings as settings_store
from ui import theme
from ui.fonts import load_fonts
from ui.overlay import OverlayWidget
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
        # Despacha o último trecho pendente (se houver) via chunk_callback,
        # de forma síncrona — ver audio_recorder.py. Não é bloqueante:
        # todo o áudio já foi transcrito aos poucos, ao vivo, enquanto a
        # gravação acontecia.
        recorder.stop()
        app_state.recording_finished.emit()


# ---------------------------------------------------------------------------
# Atalho: hold-to-talk (segurar) e duplo-clique-toggle coexistem sobre a
# MESMA combinação de teclas, configurável livremente (ver hotkeys.py e a
# aba Configurações). `held_keys`/`combo_down` rastreiam o estado físico do
# teclado; `recording_mode`/`last_release_time` decidem se a pressionada
# atual é um hold normal ou a metade de um duplo-clique.
# ---------------------------------------------------------------------------

current_hotkey_ids = []      # carregado das settings, atualizado por on_hotkey_changed
held_keys = set()            # ids canônicos fisicamente pressionados agora
combo_down = False           # a combinação INTEIRA está pressionada agora?
recording_mode = None        # None | "hold" | "toggle" — só importa enquanto is_pressed é True
last_release_time = 0.0
DOUBLE_TAP_WINDOW_S = 0.4


def _combo_fully_held():
    return bool(current_hotkey_ids) and all(k in held_keys for k in current_hotkey_ids)


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


def on_press(key):
    global combo_down
    try:
        key_id = hotkeys.id_for_pynput_key(key)
        if key_id is None:
            return
        was_full = _combo_fully_held()
        held_keys.add(key_id)
        if not was_full and _combo_fully_held() and not combo_down:
            combo_down = True
            _on_hotkey_down()
    except AttributeError:
        pass


def on_release(key):
    global combo_down
    try:
        key_id = hotkeys.id_for_pynput_key(key)
        if key_id is None:
            return
        was_full = _combo_fully_held()
        held_keys.discard(key_id)
        if was_full and not _combo_fully_held() and combo_down:
            combo_down = False
            _on_hotkey_up()
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
    global recorder, app_state, current_hotkey_ids

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    load_fonts()
    app.setFont(QFont(theme.FONT_FAMILY, 10))

    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU (sem CUDA)"

    user_settings = settings_store.load_settings()
    current_hotkey_ids = list(user_settings["hotkey"])

    app_state = AppState()
    recorder = AudioRecorder(
        level_callback=lambda lvl: app_state.audio_level.emit(lvl),
        chunk_callback=lambda chunk: app_state.audio_chunk_ready.emit(chunk),
    )

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

    def exit_app():
        app.quit()

    overlay = OverlayWidget(app_state)
    dashboard = WebDashboard(
        app_state,
        gpu_name=gpu_name,
        whisper_model=user_settings["whisper_model"],
        ollama_model=user_settings["ollama_model"],
        hotkey_ids=user_settings["hotkey"],
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

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    ctrl_handler = _make_console_ctrl_handler(app)
    kernel32.SetConsoleCtrlHandler(ctrl_handler, True)

    app_state.reload_requested.emit(user_settings["whisper_model"], user_settings["ollama_model"])

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
