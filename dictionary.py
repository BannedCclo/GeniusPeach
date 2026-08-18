"""Vocabulário que o usuário fala com frequência — usado pra enviesar o
Whisper via `initial_prompt` (ver transcriber.py/worker.py). Persistido em
%APPDATA%\\GeniusPeach\\dictionary.json — mesma pasta/padrão de
profiles.py, mas uma lista PLANA de strings, não de dicts de perfil."""

import json
import os
from pathlib import Path

from config import DICTIONARY_PROMPT_MAX_WORDS

DICTIONARY_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "GeniusPeach"
DICTIONARY_FILE = DICTIONARY_DIR / "dictionary.json"


def load_dictionary():
    try:
        with open(DICTIONARY_FILE, "r", encoding="utf-8") as f:
            words = json.load(f)
        if not isinstance(words, list):
            return []
        return [str(w).strip() for w in words if str(w).strip()]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def save_dictionary(words):
    DICTIONARY_DIR.mkdir(parents=True, exist_ok=True)
    with open(DICTIONARY_FILE, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)


def build_prompt(words):
    """Frase natural em português com o vocabulário cadastrado, usada como
    initial_prompt do faster-whisper — None se a lista estiver vazia, que o
    faster-whisper trata como "sem prompt", idêntico ao comportamento de
    antes desta feature."""
    words = [w for w in words if w.strip()]
    if not words:
        return None
    # Cap defensivo: o Whisper só considera uma janela pequena de tokens de
    # prompt — um dicionário enorme não ajuda além de um certo ponto e vira
    # uma frase ilegível nos logs/tela. Usa só as mais recentes (fim da
    # lista = ordem de cadastro), sem limitar o que fica salvo/editável na
    # tela Dicionário.
    limited = words[-DICTIONARY_PROMPT_MAX_WORDS:]
    return "Vocabulário mencionado com frequência: " + ", ".join(limited) + "."
