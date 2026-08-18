# Catálogo curado de modelos Whisper/Ollama pro modal de "Escolher modelo"
# das Configurações (ver ui/webdashboard.py). Whisper: lista exaustiva — só
# existem esses 6 tamanhos "principais" no faster-whisper. Ollama: curadoria
# — o Ollama Hub tem milhares de modelos, aqui só entra um recorte razoável
# de tamanhos/famílias comuns, boas o bastante pra corrigir texto ditado em
# português.
#
# disk/vram abaixo são ESTIMATIVAS pros modelos Ollama ainda não baixados —
# não há API confiável de metadados sem bater na internet. Pros já instalados
# (Whisper via cache local, Ollama via `ollama.list()`), o Bridge sobrescreve
# esses campos com dados reais antes de mandar pro JS.
#
# vram_gb é a mesma estimativa de "vram" acima, mas como número — usado só
# pra comparar com a VRAM real da GPU do usuário (gpu_devices.best_vram_gb)
# e acender o selo de aviso no modal. "vram" (string) continua sendo o que
# aparece pro usuário.

WHISPER_CATALOG = [
    {
        "id": "tiny", "label": "tiny", "params": "39M",
        "disk": "~75 MB", "vram": "~1 GB", "vram_gb": 1,
        "note": "Mais rápido, bem menos preciso — só pra teste rápido.",
    },
    {
        "id": "base", "label": "base", "params": "74M",
        "disk": "~145 MB", "vram": "~1 GB", "vram_gb": 1,
        "note": "Levemente mais preciso que o tiny, ainda bem leve.",
    },
    {
        "id": "small", "label": "small", "params": "244M",
        "disk": "~480 MB", "vram": "~2 GB", "vram_gb": 2,
        "note": "Bom equilíbrio pra máquinas mais simples.",
    },
    {
        "id": "medium", "label": "medium", "params": "769M",
        "disk": "~1.5 GB", "vram": "~5 GB", "vram_gb": 5,
        "note": "Padrão recomendado — boa precisão em português.",
    },
    {
        "id": "large-v2", "label": "large-v2", "params": "1.5B",
        "disk": "~3.0 GB", "vram": "~10 GB", "vram_gb": 10,
        "note": "Versão anterior do large — mais lento, alta precisão.",
    },
    {
        "id": "large-v3", "label": "large-v3", "params": "1.5B",
        "disk": "~3.1 GB", "vram": "~10 GB", "vram_gb": 10,
        "note": "Mais preciso, mais lento — exige GPU com bastante VRAM.",
    },
]

# id = nome de pull do Ollama (o que vai em `ollama.pull("qwen2.5:3b")`).
OLLAMA_CATALOG = [
    {
        "id": "qwen2.5:0.5b", "label": "Qwen 2.5 0.5B", "params": "0.5B",
        "disk": "~0.4 GB", "vram": "~1 GB", "vram_gb": 1,
        "note": "Ultraleve — qualidade de correção limitada.",
    },
    {
        "id": "qwen2.5:1.5b", "label": "Qwen 2.5 1.5B", "params": "1.5B",
        "disk": "~0.9 GB", "vram": "~2 GB", "vram_gb": 2,
        "note": "Bom pra CPU ou GPU com pouca VRAM.",
    },
    {
        "id": "qwen2.5:3b", "label": "Qwen 2.5 3B", "params": "3B",
        "disk": "~1.9 GB", "vram": "~4 GB", "vram_gb": 4,
        "note": "Padrão atual do app — equilíbrio entre velocidade e qualidade.",
    },
    {
        "id": "qwen2.5:7b", "label": "Qwen 2.5 7B", "params": "7B",
        "disk": "~4.7 GB", "vram": "~8 GB", "vram_gb": 8,
        "note": "Mais qualidade de correção, exige mais VRAM.",
    },
    {
        "id": "qwen2.5:14b", "label": "Qwen 2.5 14B", "params": "14B",
        "disk": "~9 GB", "vram": "~16 GB", "vram_gb": 16,
        "note": "Só pra GPUs com bastante VRAM — melhor qualidade da lista.",
    },
    {
        "id": "llama3.2:1b", "label": "Llama 3.2 1B", "params": "1B",
        "disk": "~1.3 GB", "vram": "~2 GB", "vram_gb": 2,
        "note": "Bem leve, alternativa da Meta ao Qwen pequeno.",
    },
    {
        "id": "llama3.2:3b", "label": "Llama 3.2 3B", "params": "3B",
        "disk": "~2.0 GB", "vram": "~4 GB", "vram_gb": 4,
        "note": "Alternativa da Meta ao Qwen 3B, boa fluência.",
    },
    {
        "id": "llama3.1:8b", "label": "Llama 3.1 8B", "params": "8B",
        "disk": "~4.7 GB", "vram": "~8 GB", "vram_gb": 8,
        "note": "Forte em seguir instruções, bom suporte a português.",
    },
    {
        "id": "gemma2:2b", "label": "Gemma 2 2B", "params": "2B",
        "disk": "~1.6 GB", "vram": "~3 GB", "vram_gb": 3,
        "note": "Modelo leve do Google, resposta rápida.",
    },
    {
        "id": "gemma2:9b", "label": "Gemma 2 9B", "params": "9B",
        "disk": "~5.4 GB", "vram": "~10 GB", "vram_gb": 10,
        "note": "Qualidade de texto mais alta, mais lento.",
    },
    {
        "id": "mistral:7b", "label": "Mistral 7B", "params": "7B",
        "disk": "~4.1 GB", "vram": "~8 GB", "vram_gb": 8,
        "note": "Clássico 7B, boa relação custo/benefício.",
    },
]


def format_bytes(n):
    """Formata uma contagem de bytes real (tamanho já instalado) pra exibição."""
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GB"
