import json
import os
from pathlib import Path

from config import OLLAMA_MODEL, WHISPER_MODEL_SIZE
from hotkeys import DEFAULT_HOTKEY

# %APPDATA%\GeniusPeach — fora da pasta do app de propósito: sobrevive a
# recompilações do .exe (que apagam dist/ inteira em build limpo) e é a
# mesma pasta seja rodando via venv ou via .exe empacotado.
SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "GeniusPeach"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULTS = {
    "whisper_model": WHISPER_MODEL_SIZE,
    "ollama_model": OLLAMA_MODEL,
    "hotkey": DEFAULT_HOTKEY,  # lista de ids canônicos — ver hotkeys.py
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

    return settings


def save_settings(settings):
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
