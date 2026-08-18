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

import audio_devices
import dictionary as dictionary_store
import gpu_devices
import hotkeys
import profiles as profiles_store
import settings as settings_store
import whisper_models
from config import OUTPUT_LANGUAGE_OPTIONS
from models_catalog import OLLAMA_CATALOG, WHISPER_CATALOG, format_bytes
from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app_state import State

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


class ModelJobThread(QThread):
    """Job descartável de download OU exclusão de UM modelo do catálogo (ver
    Bridge.download_model/delete_model) — diferente do Worker de main.py, que
    vive a aplicação inteira via moveToThread, este é criado e descartado a
    cada operação, então basta subclassar QThread e sobrescrever run(). O
    Bridge roda VÁRIOS destes ao mesmo tempo (um por modelo em andamento —
    ver Bridge._jobs), não só um por vez.

    SEM sinais Qt aqui de propósito — testado e confirmado: um Signal
    emitido de dentro de um método que roda porque foi disparado por uma
    QueuedConnection cross-thread (a conexão automática entre uma QThread e
    um slot no objeto da GUI thread) nunca chega no lado JS via
    QWebChannel, mesmo que a MESMA emissão funcione perfeitamente quando
    disparada direto por um slot chamado pelo JS (mesma thread). Isso vale
    pra QUALQUER sinal do Bridge, não só os daqui — reproduzido inclusive
    com modelCatalog. Em vez de lutar contra isso, o job só escreve o
    progresso em atributos simples (thread-safe o bastante pra isso via
    GIL) e o Bridge faz polling deles com um QTimer nativo da GUI thread
    (ver Bridge._poll_jobs) — o mesmo tipo de disparo que comprovadamente
    funciona."""

    def __init__(self, kind, model_id, action):
        super().__init__()
        self.kind = kind
        self.model_id = model_id
        self.action = action
        self.pct = -1.0
        self.status_text = ""
        self.done = False
        self.success = False
        self.message = ""

    def run(self):
        try:
            if self.action == "delete":
                self._run_delete()
                self.message = "Modelo excluído."
            elif self.kind == "whisper":
                self._run_whisper_download()
                self.message = "Modelo baixado."
            else:
                self._run_ollama_download()
                self.message = "Modelo baixado."
            self.success = True
        except Exception as exc:
            self.success = False
            self.message = str(exc)
        finally:
            self.done = True

    def _run_delete(self):
        if self.kind == "whisper":
            whisper_models.delete(self.model_id)
        else:
            import ollama
            ollama.delete(self.model_id)

    def _run_whisper_download(self):
        # Sem progresso de propósito — ver o comentário grande em
        # whisper_models.download sobre por que uma % aqui seria inventada
        # (o backend Xet do Hugging Face não expõe progresso granular, e
        # polling do disco só pulava perto do fim). O card já mostra
        # "Baixando…" indeterminado assim que o clique acontece (ver
        # app.js) — nada a atualizar enquanto isso roda de verdade.
        whisper_models.download(self.model_id)

    def _run_ollama_download(self):
        # O Ollama reporta progresso REAL por CAMADA (completed/total do
        # blob sendo baixado agora), mas reinicia a cada camada nova — um
        # modelo tem várias (pesos, template, params...). Sem agregar,
        # a % visível voltaria pra perto de 0 toda vez que uma camada nova
        # começasse, parecendo que travou/mentiu. Soma por digest (cada
        # camada só conta uma vez, o valor mais recente dela) pra dar UMA
        # % contínua do download inteiro.
        import ollama
        layers = {}  # digest -> (completed, total)
        for chunk in ollama.pull(self.model_id, stream=True):
            if chunk.digest and chunk.total:
                layers[chunk.digest] = (chunk.completed or 0, chunk.total)
                done = sum(c for c, _ in layers.values())
                total = sum(t for _, t in layers.values())
                pct = (done / total * 100) if total else -1.0
            else:
                pct = -1.0
            self.pct = pct
            self.status_text = chunk.status or ""


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
    # Lista de perfis + qual está ativo — emitido depois de qualquer
    # criação/edição/exclusão/troca, pra Ditado (select) e Perfis (lista)
    # ficarem sincronizados sem cada um pedir separadamente.
    profilesChanged = Signal("QVariantList", str)
    profileStatusMessage = Signal(str)
    # Catálogo completo (baixados + disponíveis pra baixar) pro modal de
    # "Escolher modelo" das Configurações — ver _build_catalog.
    modelCatalog = Signal("QVariantMap")
    modelJobProgress = Signal(str, str, float, str)
    modelJobFinished = Signal(str, str, str, bool, str)
    # Lista de palavras do Dicionário (ver dictionary.py) — emitido depois
    # de qualquer adição/exclusão/reinício, pra tela Dicionário refletir.
    dictionaryChanged = Signal("QVariantList")
    dictionaryStatusMessage = Signal(str)

    def __init__(
        self,
        app_state,
        whisper_model,
        ollama_model,
        hotkey_ids,
        cycle_profile_hotkey_ids,
        device_id,
        profiles,
        profile_id,
        dictionary,
        input_device,
        output_language,
        on_exit,
        on_start_recording,
        on_stop_recording,
    ):
        super().__init__()
        self.app_state = app_state
        self._whisper = whisper_model
        self._ollama = ollama_model
        self._hotkey = list(hotkey_ids)  # lista de ids canônicos, ver hotkeys.py
        self._cycle_profile_hotkey = list(cycle_profile_hotkey_ids)
        self._device = device_id
        self._profiles = list(profiles)
        self._profile_id = profile_id
        self._dictionary = list(dictionary)
        self._input_device = input_device
        self._output_language = output_language
        self._on_exit = on_exit
        self._on_start_recording = on_start_recording
        self._on_stop_recording = on_stop_recording

        # Jobs de download/exclusão de modelo em andamento agora, um por
        # (kind, model_id) — VÁRIOS podem rodar ao mesmo tempo (baixar dois
        # modelos em paralelo, ou trocar de modelo em uso enquanto outro
        # baixa em segundo plano); só trava duas operações no MESMO modelo
        # ao mesmo tempo (ver download_model/delete_model). Guardar a
        # thread aqui mantém a referência Python viva enquanto ela roda —
        # senão o GC podia derrubar o QThread no meio da execução.
        self._jobs = {}
        # Progresso por job já reportado da última vez (pra só reemitir
        # modelJobProgress quando o valor de fato mudou) — ver _poll_jobs.
        self._jobs_last_pct = {}
        # QTimer nativo da GUI thread: os sinais de progresso/conclusão dos
        # jobs de modelo são emitidos SÓ daqui, nunca de dentro de um
        # método disparado por uma QueuedConnection cross-thread (ver o
        # comentário grande em ModelJobThread sobre por quê).
        self._job_poll_timer = QTimer(self)
        self._job_poll_timer.timeout.connect(self._poll_jobs)
        self._job_poll_timer.start(200)

        # Flags que ligam o "Recarregando modelos…" emitido em save_settings
        # ao fim de verdade do carregamento (ver _on_app_state_changed) —
        # _was_loading rastreia a transição LOADING -> outro estado
        # (inclusive no boot, quando nenhum reload foi pedido por Salvar);
        # _reload_pending só fica True quando ESSA transição deve virar
        # mensagem, isto é, quando ela começou por um Salvar com modelo ou
        # dispositivo trocado.
        self._was_loading = False
        self._reload_pending = False
        app_state.state_changed.connect(self._on_app_state_changed)

        # Mantém o painel sincronizado quando o perfil ativo muda por FORA
        # da tela de Perfis — hoje só o atalho global de ciclar perfis (ver
        # main.py), mas o canal é genérico pra qualquer origem futura.
        app_state.active_profile_changed.connect(self._on_active_profile_changed)

    # ------------------------------------------------------ Python -> página

    def info_payload(self):
        devices = gpu_devices.list_devices()
        input_devices = audio_devices.list_devices()
        return {
            "gpu": gpu_devices.resolve(self._device, devices)["label"],
            "whisper": self._whisper,
            "ollama": self._ollama,
            "hotkey": list(self._hotkey),
            "hotkey_label": hotkeys.label_for(self._hotkey),
            "cycle_profile_hotkey": list(self._cycle_profile_hotkey),
            "cycle_profile_hotkey_label": hotkeys.label_for(self._cycle_profile_hotkey),
            "device": self._device,
            # Só faz sentido mostrar o seletor se houver de fato uma
            # escolha — uma GPU só + CPU já conta como duas opções.
            "device_options": [[d["id"], d["label"]] for d in devices],
            "profile_id": self._profile_id,
            "profile_options": [[p["id"], p["name"]] for p in self._profiles],
            "profiles": list(self._profiles),
            "dictionary": list(self._dictionary),
            "input_device": self._input_device,
            "input_device_options": [[d["id"], d["label"]] for d in input_devices],
            "output_language": self._output_language,
            "output_language_options": [[code, label] for code, label in OUTPUT_LANGUAGE_OPTIONS],
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

    @Slot(str)
    def copy_to_clipboard(self, text):
        # Área de transferência nativa do Qt, não a Clipboard API do
        # navegador — a página roda de um file:// dentro do QWebEngineView
        # sem nenhum handler de permissão configurado, então
        # navigator.clipboard.writeText ficaria pendendo/falhando sem
        # aviso nenhum (ver ui/web/app.js, copyText).
        QGuiApplication.clipboard().setText(text)

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

    # -------------------------------------------------- catálogo de modelos

    def _build_catalog(self):
        whisper_installed = whisper_models.cached_sizes()
        whisper_list = []
        for entry in WHISPER_CATALOG:
            e = dict(entry)
            e["installed"] = e["id"] in whisper_installed
            if e["installed"]:
                real = whisper_models.downloaded_bytes(e["id"])
                if real:
                    e["disk"] = format_bytes(real)
            whisper_list.append(e)

        try:
            import ollama
            installed = {m.model: m for m in ollama.list().models}
        except Exception:
            installed = {}

        by_id = {}
        for entry in OLLAMA_CATALOG:
            e = dict(entry)
            e["installed"] = False
            by_id[e["id"]] = e

        for model_id, info in installed.items():
            e = by_id.get(model_id)
            if e is None:
                # Instalado mas fora do catálogo curado (ex.: baixado via
                # `ollama pull` fora do app) — não pode simplesmente sumir
                # da lista, senão a tela regride em relação ao comportamento
                # antigo (que listava tudo que `ollama list` retornasse).
                e = {"id": model_id, "label": model_id, "params": "", "vram": "", "note": "Instalado localmente (fora do catálogo curado)."}
                by_id[model_id] = e
            e["installed"] = True
            e["disk"] = format_bytes(info.size)
            details = getattr(info, "details", None)
            if details is not None and getattr(details, "parameter_size", None):
                e["params"] = details.parameter_size

        return {
            "whisper": whisper_list,
            "ollama": list(by_id.values()),
            # VRAM real da melhor GPU CUDA detectada (0 = só CPU) — usada só
            # pra acender o selo de aviso no modal, nunca pra bloquear nada
            # (ver gpu_devices.best_vram_gb).
            "available_vram_gb": gpu_devices.best_vram_gb(),
        }

    @Slot()
    def request_model_catalog(self):
        self.modelCatalog.emit(self._build_catalog())

    @Slot(str, str)
    def download_model(self, kind, model_id):
        key = (kind, model_id)
        if key in self._jobs:
            self.modelJobFinished.emit(kind, model_id, "download", False, "Esse modelo já está sendo baixado.")
            return
        self._start_job(kind, model_id, "download")

    @Slot(str, str)
    def delete_model(self, kind, model_id):
        key = (kind, model_id)
        if key in self._jobs:
            self.modelJobFinished.emit(kind, model_id, "delete", False, "Já existe uma operação em andamento nesse modelo.")
            return
        current = self._whisper if kind == "whisper" else self._ollama
        if model_id == current:
            self.modelJobFinished.emit(kind, model_id, "delete", False, "Não é possível excluir o modelo em uso.")
            return
        self._start_job(kind, model_id, "delete")

    def _start_job(self, kind, model_id, action):
        key = (kind, model_id)
        thread = ModelJobThread(kind, model_id, action)
        self._jobs[key] = thread
        self._jobs_last_pct[key] = None
        thread.start()

    def _poll_jobs(self):
        # Chamado pelo QTimer nativo da GUI thread — só daqui que os sinais
        # de job de modelo são emitidos (ver ModelJobThread e o comentário
        # sobre QueuedConnection cross-thread não chegar no QWebChannel).
        finished = []
        for key, thread in self._jobs.items():
            kind, model_id = key
            if thread.done:
                finished.append((key, thread))
                continue
            # Exclusão nunca tem progresso mensurável (ver ModelJobThread) —
            # nem vale emitir, o JS trata isso mostrando um spinner fixo
            # assim que o job começa, sem esperar sinal nenhum.
            if thread.action != "download":
                continue
            if self._jobs_last_pct.get(key) != thread.pct:
                self._jobs_last_pct[key] = thread.pct
                self.modelJobProgress.emit(kind, model_id, thread.pct, thread.status_text)

        for key, thread in finished:
            kind, model_id = key
            self._jobs.pop(key, None)
            self._jobs_last_pct.pop(key, None)
            self.modelJobFinished.emit(kind, model_id, thread.action, thread.success, thread.message)

        if finished:
            self.modelCatalog.emit(self._build_catalog())

    # ------------------------------------------------- dicionário de vocabulário

    def _push_dictionary(self):
        """Persiste + reaplica o viés ao vivo no Whisper (sem reload
        nenhum, ver worker.set_dictionary_prompt) + atualiza a tela."""
        dictionary_store.save_dictionary(self._dictionary)
        self.app_state.dictionary_changed.emit(dictionary_store.build_prompt(self._dictionary))
        self.dictionaryChanged.emit(list(self._dictionary))

    @Slot()
    def request_dictionary(self):
        self.dictionaryChanged.emit(list(self._dictionary))

    @Slot(str)
    def add_dictionary_word(self, word):
        word = word.strip()
        if not word:
            return
        normalized = word.lower()
        if any(w.lower() == normalized for w in self._dictionary):
            self.dictionaryStatusMessage.emit(f'"{word}" já está no Dicionário.')
            return
        self._dictionary.append(word)
        self._push_dictionary()
        self.dictionaryStatusMessage.emit(f'"{word}" adicionada ao Dicionário.')

    @Slot(str)
    def delete_dictionary_word(self, word):
        self._dictionary = [w for w in self._dictionary if w != word]
        self._push_dictionary()
        self.dictionaryStatusMessage.emit("Palavra removida do Dicionário.")

    @Slot()
    def reset_dictionary(self):
        self._dictionary = []
        self._push_dictionary()
        self.dictionaryStatusMessage.emit("Dicionário reiniciado — a IA volta a não ter viés de vocabulário.")

    @Slot(str, str, "QVariantList", "QVariantList", str, str, str)
    def save_settings(
        self,
        whisper_model,
        ollama_model,
        hotkey_ids,
        cycle_profile_hotkey_ids,
        device_id,
        input_device_id,
        output_language,
    ):
        # hotkey_ids/cycle_profile_hotkey_ids chegam do JS como listas
        # soltas de ids, na ordem em que o usuário apertou durante a
        # captura — canoniza aqui (mesma ordem de exibição sempre) antes de
        # persistir.
        hotkey_ids = hotkeys.canonical_order(str(k) for k in hotkey_ids)
        cycle_profile_hotkey_ids = hotkeys.canonical_order(str(k) for k in cycle_profile_hotkey_ids)

        settings_store.save_settings({
            "whisper_model": whisper_model,
            "ollama_model": ollama_model,
            "hotkey": hotkey_ids,
            "cycle_profile_hotkey": cycle_profile_hotkey_ids,
            "device": device_id,
            "input_device": input_device_id,
            "output_language": output_language,
        })

        messages = ["Configurações salvas."]

        # Trocar o dispositivo exige recarregar o Whisper igual a trocar de
        # modelo (não dá pra mover um WhisperModel já carregado de uma GPU
        # pra outra, ou de GPU pra CPU, em tempo de execução) — por isso
        # entra na MESMA condição de reload_requested.
        if whisper_model != self._whisper or ollama_model != self._ollama or device_id != self._device:
            self._whisper = whisper_model
            self._ollama = ollama_model
            self._device = device_id
            self.app_state.reload_requested.emit(whisper_model, ollama_model, device_id)
            messages.append("Recarregando modelos…")
            self._reload_pending = True

        if set(hotkey_ids) != set(self._hotkey):
            self._hotkey = hotkey_ids
            self.app_state.hotkey_changed.emit(hotkey_ids)
            messages.append(f"Atalho agora é {hotkeys.label_for(hotkey_ids)}.")

        if set(cycle_profile_hotkey_ids) != set(self._cycle_profile_hotkey):
            self._cycle_profile_hotkey = cycle_profile_hotkey_ids
            self.app_state.cycle_profile_hotkey_changed.emit(cycle_profile_hotkey_ids)
            messages.append(f"Atalho de ciclar perfis agora é {hotkeys.label_for(cycle_profile_hotkey_ids)}.")

        # Trocar de microfone é independente do Whisper/Ollama (sounddevice
        # vs. CTranslate2) — nunca deveria disparar reload_requested, que é
        # pesado e sem necessidade nenhuma pra isso.
        if input_device_id != self._input_device:
            self._input_device = input_device_id
            self.app_state.input_device_changed.emit(input_device_id)
            messages.append("Microfone atualizado.")

        if output_language != self._output_language:
            self._output_language = output_language
            self.app_state.output_language_changed.emit(output_language)
            label = dict(OUTPUT_LANGUAGE_OPTIONS).get(output_language, output_language)
            messages.append(f"Idioma de saída agora é {label}.")

        self.push_info()
        self.statusMessage.emit(" ".join(messages))

    def _on_app_state_changed(self, state):
        # Só interessa a transição LOADING -> qualquer outro estado (se
        # falhar, o Worker nunca sai de LOADING — ver worker.load_models —
        # então este bloco simplesmente não dispara em caso de erro).
        if state == State.LOADING:
            self._was_loading = True
            return
        if self._was_loading:
            self._was_loading = False
            if self._reload_pending:
                self._reload_pending = False
                self.statusMessage.emit("Configurações salvas. Modelos carregados.")

    @Slot(str)
    def select_profile(self, profile_id):
        """Troca qual perfil é usado no PRÓXIMO ditado — aplica na hora
        (sem precisar de "Salvar", diferente da tela de Configurações) e
        persiste, pra sobreviver a um reinício do app."""
        if profile_id == self._profile_id:
            return
        profile = profiles_store.find(self._profiles, profile_id)
        if profile is None:
            return
        self._profile_id = profile_id
        settings_store.save_settings({"profile_id": profile_id})
        self.app_state.profile_changed.emit(profile["prompt"])
        self.app_state.active_profile_changed.emit(profile_id, profile["name"])
        self.profilesChanged.emit(list(self._profiles), self._profile_id)

    @Slot(str, str, str)
    def save_profile(self, profile_id, name, prompt):
        """profile_id vazio = cria um novo; senão edita o existente."""
        if profile_id == profiles_store.RAW_PROFILE_ID:
            self.profileStatusMessage.emit("Este perfil é fixo e não pode ser editado.")
            return

        name = name.strip()
        prompt = prompt.strip()
        if not name or not prompt:
            self.profileStatusMessage.emit("Nome e prompt não podem ficar vazios.")
            return

        if profile_id:
            target = profiles_store.find(self._profiles, profile_id)
            if target is None:
                return
            target["name"] = name
            target["prompt"] = prompt
        else:
            profile_id = profiles_store.new_id()
            self._profiles.append({"id": profile_id, "name": name, "prompt": prompt})

        profiles_store.save_profiles(self._profiles)

        # Se o perfil editado é o que está ATIVO agora, o prompt pode ter
        # mudado — repassa pro Worker na hora, sem precisar selecionar o
        # perfil de novo pra "ativar" a mudança.
        if profile_id == self._profile_id:
            updated = profiles_store.find(self._profiles, profile_id)
            self.app_state.profile_changed.emit(updated["prompt"])

        self.profilesChanged.emit(list(self._profiles), self._profile_id)
        self.profileStatusMessage.emit("Perfil salvo.")

    @Slot(str)
    def delete_profile(self, profile_id):
        if profile_id == profiles_store.RAW_PROFILE_ID:
            self.profileStatusMessage.emit("Este perfil é fixo e não pode ser excluído.")
            return

        # O perfil fixo garante que a lista nunca fica vazia depois disto —
        # sem ele, seria preciso um guard separado contra excluir o último
        # perfil restante.
        self._profiles = [p for p in self._profiles if p["id"] != profile_id]
        profiles_store.save_profiles(self._profiles)

        if self._profile_id == profile_id:
            # O perfil ativo foi excluído — cai pro primeiro que sobrou em
            # vez de deixar o ditado seguinte sem prompt nenhum.
            self._profile_id = self._profiles[0]["id"]
            settings_store.save_settings({"profile_id": self._profile_id})
            self.app_state.profile_changed.emit(self._profiles[0]["prompt"])
            self.app_state.active_profile_changed.emit(self._profile_id, self._profiles[0]["name"])

        self.profilesChanged.emit(list(self._profiles), self._profile_id)
        self.profileStatusMessage.emit("Perfil excluído.")

    def _on_active_profile_changed(self, profile_id, profile_name):
        # Chamado sempre que o perfil ativo muda — inclusive quando fomos
        # NÓS que emitimos (select_profile/delete_profile acima também
        # disparam este mesmo sinal, ver app_state.py). Guard evita
        # reemitir profilesChanged à toa nesse caso; quando a origem é o
        # atalho global de ciclar perfis (main.py), self._profile_id ainda
        # está desatualizado e este é o único lugar que o corrige.
        if profile_id == self._profile_id:
            return
        self._profile_id = profile_id
        self.profilesChanged.emit(list(self._profiles), self._profile_id)


class WebDashboard(QWidget):
    """Janela normal (com moldura), aberta pela bandeja. Fechar pelo X só
    esconde — quem encerra o app é o "Encerrar programa" da barra lateral,
    o "Sair" da bandeja, ou Ctrl+C. Mesma assinatura e mesmo ciclo de vida
    do painel anterior em widgets nativos."""

    def __init__(
        self,
        app_state,
        whisper_model,
        ollama_model,
        hotkey_ids,
        cycle_profile_hotkey_ids,
        device_id,
        profiles,
        profile_id,
        dictionary,
        input_device,
        output_language,
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

        self.bridge = Bridge(
            app_state,
            whisper_model,
            ollama_model,
            hotkey_ids,
            cycle_profile_hotkey_ids,
            device_id,
            profiles,
            profile_id,
            dictionary,
            input_device,
            output_language,
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
        # audio_level já chega throttled na fonte (AudioRecorder, ver
        # config.AUDIO_LEVEL_INTERVAL_MS) — repassa direto pro JS, sem
        # limitar de novo aqui.
        app_state.audio_level.connect(lambda lvl: self.bridge.audioLevel.emit(float(lvl)))
        app_state.raw_text_ready.connect(self.bridge.rawText.emit)
        app_state.optimized_text_ready.connect(self.bridge.optimizedText.emit)
        app_state.error_occurred.connect(self.bridge.errorText.emit)
        app_state.history_entry_added.connect(self._on_history_entry)
        app_state.ollama_online_changed.connect(self.bridge.ollamaStatus.emit)

    def _on_state_changed(self, state):
        self.bridge.stateChanged.emit(STATE_NAMES.get(state, "IDLE"))

    def _on_history_entry(self, entry):
        self.bridge.historyAdded.emit({
            "time": datetime.now().strftime("%H:%M:%S"),
            "raw": entry.get("raw_text", ""),
            "text": entry.get("optimized_text", ""),
            "transcribe": f"{entry.get('transcribe_time', 0):.2f}s",
            "optimize": f"{entry.get('optimize_time', 0):.2f}s",
        })

    def closeEvent(self, event):
        event.ignore()
        self.hide()
