import json
import os
from pathlib import Path

import audio_devices
import gpu_devices
import profiles as profiles_store
from config import (
    OLLAMA_MODEL,
    WHISPER_MODEL_SIZE,
    DEFAULT_OUTPUT_LANGUAGE,
    OUTPUT_LANGUAGE_OPTIONS,
)
from hotkeys import DEFAULT_CYCLE_PROFILE_HOTKEY, DEFAULT_HOTKEY

# %APPDATA%\GeniusPeach — fora da pasta do app de propósito: sobrevive a
# recompilações do .exe (que apagam dist/ inteira em build limpo) e é a
# mesma pasta seja rodando via venv ou via .exe empacotado.
SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "GeniusPeach"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULTS = {
    "whisper_model": WHISPER_MODEL_SIZE,
    "ollama_model": OLLAMA_MODEL,
    "hotkey": DEFAULT_HOTKEY,  # lista de ids canônicos — ver hotkeys.py
    # Atalho global de CICLAR perfis (main.py) — lista de ids no mesmo
    # esquema do "hotkey" acima, capturado do mesmo jeito na tela de
    # Configurações.
    "cycle_profile_hotkey": DEFAULT_CYCLE_PROFILE_HOTKEY,
    # Melhor dispositivo disponível nesta máquina (mais VRAM, ou CPU se não
    # houver GPU CUDA) — calculado na hora, não é um valor fixo como os de
    # cima. Ver gpu_devices.py.
    "device": gpu_devices.pick_default(),
    # Perfil de tratamento ativo (qual prompt usar no Ollama) — ver
    # profiles.py. Perfis em si NÃO ficam aqui, só o id do que está em uso.
    "profile_id": profiles_store.DEFAULT_PROFILE_ID,
    # Microfone favorito (dispositivo de ENTRADA de áudio, ver
    # audio_devices.py) — "default" deixa o SO decidir, sem fixar um
    # device_id específico.
    "input_device": audio_devices.DEFAULT_DEVICE_ID,
    # Idioma de SAÍDA do texto corrigido pelo Ollama (ver config.py) — só
    # afeta o texto final, não a língua em que o Whisper transcreve.
    "output_language": DEFAULT_OUTPUT_LANGUAGE,
}

# Lista fixa (o Whisper não expõe os tamanhos disponíveis por API). Fica aqui
# junto do resto da configuração para não depender de nenhum módulo de UI —
# quem consome é o painel, seja ele qual for.
WHISPER_MODEL_OPTIONS = [
    ("tiny", "tiny — mais rápido, menos preciso"),
    ("base", "base"),
    ("small", "small"),
    ("medium", "medium"),
    ("large-v3", "large-v3 — mais preciso, mais lento"),
]


def load_settings():
    settings = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for key in DEFAULTS:
            if saved.get(key):
                settings[key] = saved[key]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    # settings.json de antes desta versão guardava o atalho como uma
    # string única (ex.: "alt_l"), não uma lista de ids — sem isso, um
    # settings.json existente faria o resto do app iterar as LETRAS da
    # string como se fossem teclas separadas.
    if isinstance(settings["hotkey"], str):
        settings["hotkey"] = [settings["hotkey"]]

    # O dispositivo salvo pode não existir mais nesta máquina (GPU trocada/
    # removida, ou o settings.json veio de outro computador) — cai pro
    # melhor disponível em vez de travar o carregamento do Whisper.
    devices = gpu_devices.list_devices()
    settings["device"] = gpu_devices.resolve(settings["device"], devices)["id"]

    # Mesma lógica do device (GPU): o microfone salvo pode ter sido
    # desconectado, ou o settings.json pode vir de outra máquina — cai pro
    # "Padrão do sistema" em vez de travar a gravação.
    input_devices = audio_devices.list_devices()
    settings["input_device"] = audio_devices.resolve(settings["input_device"], input_devices)["id"]

    # Mesma lógica do dispositivo: o perfil salvo pode ter sido excluído
    # (ou vir de outra máquina/perfis.json diferente) — cai pro primeiro
    # perfil disponível em vez de apontar pra um id inexistente.
    all_profiles = profiles_store.load_profiles()
    if profiles_store.find(all_profiles, settings["profile_id"]) is None:
        settings["profile_id"] = all_profiles[0]["id"]

    # Idioma salvo pode vir de uma versão antiga do settings.json (campo
    # nem existia) ou de um código removido do catálogo — cai pro padrão
    # em vez de mandar um código desconhecido pro Ollama.
    valid_languages = {code for code, _ in OUTPUT_LANGUAGE_OPTIONS}
    if settings["output_language"] not in valid_languages:
        settings["output_language"] = DEFAULT_OUTPUT_LANGUAGE

    return settings


def save_settings(settings):
    """Faz merge com o settings.json existente em vez de sobrescrever tudo —
    algumas ações da UI salvam só UM campo (ex.: trocar o perfil ativo no
    ditado, sem passar pela tela de Configurações inteira); sobrescrever o
    arquivo inteiro com um dict parcial apagaria os outros campos salvos."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    current = {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            current = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    current.update(settings)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
