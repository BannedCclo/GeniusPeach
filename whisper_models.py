# Detecção/download/exclusão de modelos Whisper em cache local (faster-whisper
# baixa do Hugging Face Hub por baixo dos panos — ver ui/webdashboard.py, que
# usa isto pro modal de "Escolher modelo").

import os

from huggingface_hub import scan_cache_dir
from huggingface_hub.constants import HF_HUB_CACHE

_REPO_PREFIX = "Systran/faster-whisper-"


def _repo_id(size):
    return _REPO_PREFIX + size


def _repo_path(size):
    return os.path.join(HF_HUB_CACHE, "models--Systran--faster-whisper-" + size)


def cached_sizes():
    """Tamanhos com pelo menos uma revisão em cache."""
    try:
        info = scan_cache_dir()
    except Exception:
        return set()
    return {
        repo.repo_id[len(_REPO_PREFIX):]
        for repo in info.repos
        if repo.repo_id.startswith(_REPO_PREFIX)
    }


def downloaded_bytes(size):
    """Soma bytes em disco do repo — mais barato que scan_cache_dir() pra
    chamar em loop de progresso (varre só a pasta do modelo, não o cache HF
    inteiro, que pode ter repos de outros projetos).

    Soma só blobs/ (onde os bytes baixados realmente residem), não
    snapshots/ — snapshots/ é feito de symlinks (ou, sem privilégio pra
    symlink, cópias) pros MESMOS arquivos de blobs/; contar as duas pastas
    dobra o tamanho reportado."""
    blobs_dir = os.path.join(_repo_path(size), "blobs")
    total = 0
    for root, _dirs, files in os.walk(blobs_dir):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def download(size):
    """Bloqueante — chamar de dentro de uma thread separada da GUI.
    snapshot_download (por baixo do download_model) é resumível/idempotente:
    chamar de novo após uma queda completa o que faltava, sem corromper nada.

    Sem progresso granular de propósito: os repos do Whisper baixam pelo
    backend Xet (pacote hf_xet, instalado — confirmado no código-fonte de
    huggingface_hub._snapshot_download que ele NÃO repassa progresso
    byte-a-byte pro tqdm_class de fora, só atualiza a barra quando cada
    arquivo termina) e o tamanho em disco (ver downloaded_bytes) só cresce
    em blocos grandes e espaçados durante o download — as duas fontes
    davam uma % que ficava parada minutos e pulava no fim. Melhor mostrar
    "baixando" honesto (ver ui/web/app.js, indicador indeterminado) do que
    uma porcentagem que mente."""
    from faster_whisper.utils import download_model
    download_model(size)


def delete(size):
    """Remove um tamanho específico do cache sem tocar nos outros."""
    info = scan_cache_dir()
    repo = next((r for r in info.repos if r.repo_id == _repo_id(size)), None)
    if repo is None:
        return
    strategy = info.delete_revisions(*(rev.commit_hash for rev in repo.revisions))
    strategy.execute()
