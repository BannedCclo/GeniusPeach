"""Enumera dispositivos de ENTRADA de áudio (microfones) pro seletor de
Configurações (ver ui/webdashboard.py, audio_recorder.py).

Cada microfone físico aparece várias vezes em sounddevice.query_devices()
— uma por host API (MME, Windows DirectSound, Windows WASAPI, Windows
WDM-KS; comportamento normal do Windows, confirmado nesta máquina) — por
isso filtramos por UM host API só. WASAPI é a API moderna de baixa
latência do Windows, a que a maioria dos apps de áudio usa por padrão;
se por algum motivo ela não existir nesta máquina (driver muito antigo),
cai pro primeiro host API que tiver alguma entrada, só pra continuar
deduplicando em vez de listar cada microfone 3-4 vezes."""

import sounddevice as sd

DEFAULT_DEVICE_ID = "default"


def _fallback_hostapi_index():
    try:
        hostapis = sd.query_hostapis()
    except Exception:
        return None
    for i, api in enumerate(hostapis):
        if api.get("name") == "Windows WASAPI":
            return i
    for i, api in enumerate(hostapis):
        if api.get("device_count", 0) > 0:
            return i
    return None


def list_devices():
    """[{"id", "label", "device_index"}, ...] — "default" ("Padrão do
    sistema", device_index=None) sempre primeiro, deixando o SO decidir;
    útil pra quem troca de fone/microfone com frequência."""
    devices = [{"id": DEFAULT_DEVICE_ID, "label": "Padrão do sistema", "device_index": None}]
    try:
        hostapi_index = _fallback_hostapi_index()
        for idx, info in enumerate(sd.query_devices()):
            if info.get("max_input_channels", 0) <= 0:
                continue
            if hostapi_index is not None and info.get("hostapi") != hostapi_index:
                continue
            devices.append({"id": str(idx), "label": info["name"], "device_index": idx})
    except Exception as e:
        print(f"[GeniusPeach][aviso] Falha ao enumerar microfones: {e}")
    return devices


def resolve(device_id, devices=None):
    """Dict do dispositivo pro id salvo. Cai pra "Padrão do sistema" se o
    id não existir mais (microfone desconectado, ou settings.json de outra
    máquina) — mesmo padrão de gpu_devices.resolve."""
    devices = devices if devices is not None else list_devices()
    for d in devices:
        if d["id"] == device_id:
            return d
    return devices[0]
