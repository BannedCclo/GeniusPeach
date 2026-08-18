"""Enumera os dispositivos de computação disponíveis pro Whisper.

O faster-whisper (motor por trás da transcrição, via CTranslate2) só
acelera em GPUs NVIDIA através de CUDA — não existe caminho de aceleração
pra placas integradas (Intel UHD, AMD Vega/Radeon integrada) nem pra GPUs
dedicadas de outros fabricantes (AMD, Intel Arc): CTranslate2 só suporta
os dispositivos "cuda" e "cpu" (confirmado direto na assinatura de
`ctranslate2.Translator.__init__`, que é o que `WhisperModel` usa por
baixo). Por isso a lista aqui nunca inclui uma placa integrada como opção
de execução — ela cairia pra CPU do mesmo jeito, então rotulá-la como se
fosse um dispositivo à parte seria enganoso.

Cada GPU CUDA detectada vira uma opção, ordenadas por VRAM (a maior
primeiro — mais VRAM cabe modelos maiores/mais precisos). CPU sempre entra
como a última opção, disponível mesmo sem nenhuma GPU."""

import torch

CPU_DEVICE_ID = "cpu"


def list_devices():
    """[{"id", "label", "kind", "device_index", "vram_gb"}, ...], ordenado
    por VRAM decrescente — CPU sempre por último."""
    devices = []

    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            vram_gb = props.total_memory / (1024 ** 3)
            devices.append({
                "id": f"cuda:{i}",
                "label": f"{props.name} ({vram_gb:.0f} GB)",
                "kind": "cuda",
                "device_index": i,
                "vram_gb": vram_gb,
            })

    devices.sort(key=lambda d: d["vram_gb"], reverse=True)

    devices.append({
        "id": CPU_DEVICE_ID,
        "label": "CPU (sem aceleração de GPU)",
        "kind": "cpu",
        "device_index": None,
        "vram_gb": 0.0,
    })

    return devices


def pick_default(devices=None):
    """Melhor opção disponível: a GPU com mais VRAM, senão CPU. Como a
    lista já vem ordenada por VRAM (CPU sempre por último), é sempre a
    primeira entrada."""
    devices = devices if devices is not None else list_devices()
    return devices[0]["id"]


def resolve(device_id, devices=None):
    """Dict do dispositivo pro id salvo. Cai pra melhor opção disponível se
    o id não existir mais (ex.: GPU salva foi removida/trocada, ou o app
    está rodando numa máquina diferente da que gerou o settings.json)."""
    devices = devices if devices is not None else list_devices()
    for d in devices:
        if d["id"] == device_id:
            return d
    return devices[0]


def best_vram_gb(devices=None):
    """Maior VRAM entre as GPUs CUDA detectadas, 0.0 se não houver nenhuma
    (só CPU) — usado pra avisar no modal de modelos (ver ui/webdashboard.py)
    quando um modelo do catálogo provavelmente não cabe na placa do
    usuário. Não é uma trava: o Whisper na CPU ignora VRAM, e o Ollama
    costuma descarregar parte do modelo pra CPU em vez de falhar — por
    isso isto vira só um aviso, nunca um bloqueio."""
    devices = devices if devices is not None else list_devices()
    cuda_vram = [d["vram_gb"] for d in devices if d["kind"] == "cuda"]
    return max(cuda_vram) if cuda_vram else 0.0


def compute_type_for(kind):
    # float16 é a otimização de VRAM/velocidade em GPU; na CPU a maioria
    # não acelera float16 de verdade, então int8 é o padrão recomendado
    # pelo próprio faster-whisper pra esse caso (bom equilíbrio
    # velocidade/qualidade sem GPU).
    return "float16" if kind == "cuda" else "int8"
