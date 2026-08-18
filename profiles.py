"""Perfis de tratamento de áudio: cada um guarda um prompt diferente pra
passar ao Ollama na hora de corrigir o texto transcrito (ver
worker.finish_session/text_optimizer.py). Persistidos em
%APPDATA%\\GeniusPeach\\profiles.json — mesma pasta de settings.json, mas
sem importar de lá pra evitar import circular (settings.py importa o id do
perfil padrão daqui)."""

import json
import os
import uuid
from pathlib import Path

from config import SYSTEM_PROMPT

PROFILES_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "GeniusPeach"
PROFILES_FILE = PROFILES_DIR / "profiles.json"

DEFAULT_PROFILE_ID = "default"
# Reaproveita o SYSTEM_PROMPT que já existia fixo em config.py — quem
# atualiza de uma versão sem perfis não perde o comportamento atual.
DEFAULT_PROFILE = {
    "id": DEFAULT_PROFILE_ID,
    "name": "Padrão",
    "prompt": SYSTEM_PROMPT,
}

# Perfil fixo, sempre presente, injetado em TODA leitura em vez de vivido no
# arquivo (ver load/save_profiles abaixo) — não pode ser editado nem
# excluído (guardado em ui/webdashboard.py). `prompt: None` é o sinal que
# worker.finish_session usa pra pular o Ollama de propósito, entregando a
# transcrição crua do Whisper como resultado final.
RAW_PROFILE_ID = "raw"
RAW_PROFILE = {
    "id": RAW_PROFILE_ID,
    "name": "Transcrição bruta",
    "prompt": None,
    "builtin": True,
}


def load_profiles():
    """Sempre devolve pelo menos 2 perfis: o fixo (bruto, sem Ollama) mais
    o(s) salvo(s) pelo usuário — nunca uma lista sem nada selecionável."""
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            profiles = json.load(f)
        if not isinstance(profiles, list) or not profiles:
            profiles = [dict(DEFAULT_PROFILE)]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        profiles = [dict(DEFAULT_PROFILE)]

    # O perfil fixo nunca é persistido (ver save_profiles) — remove
    # qualquer cópia que tenha ido parar no arquivo por edição manual, pra
    # nunca haver dois com o mesmo id depois de prepender o de verdade.
    profiles = [p for p in profiles if p.get("id") != RAW_PROFILE_ID]
    return [dict(RAW_PROFILE)] + profiles


def save_profiles(profiles):
    """Nunca grava o perfil fixo em disco — ele é código, não dado; sempre
    reinjetado por load_profiles(), então persisti-lo só duplicaria."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    to_save = [p for p in profiles if p.get("id") != RAW_PROFILE_ID]
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)


def new_id():
    return uuid.uuid4().hex[:12]


def find(profiles, profile_id):
    for p in profiles:
        if p["id"] == profile_id:
            return p
    return None
