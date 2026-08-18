import time
import numpy as np
from faster_whisper import WhisperModel
import gpu_devices
from config import (
    WHISPER_MODEL_SIZE,
    WHISPER_VAD_FILTER,
    WHISPER_VAD_MIN_SILENCE_MS,
    SAMPLE_RATE,
)

# Lista de frases fantasmas clássicas do Whisper em português em silêncio
HALLUCINATIONS = {
    "e aí.", "e aí", "obrigado.", "obrigado", "tchau.",
    "legendas pela comunidade amara.org", "inscreva-se no canal."
}

class Transcriber:
    def __init__(self, model_size=None, device_id=None):
        model_size = model_size or WHISPER_MODEL_SIZE

        print("[GeniusPeach] Verificando aceleração de hardware...")
        devices = gpu_devices.list_devices()
        device = gpu_devices.resolve(device_id, devices) if device_id else devices[0]
        self.device = device

        if device["kind"] == "cuda":
            print(f"[GeniusPeach] GPU ativa: {device['label']}")
        else:
            print("[GeniusPeach] Sem GPU dedicada disponível — rodando na CPU (latência maior).")

        kwargs = {
            "device": device["kind"],
            "compute_type": gpu_devices.compute_type_for(device["kind"]),
        }
        if device["device_index"] is not None:
            kwargs["device_index"] = device["device_index"]

        print(f"[GeniusPeach] Carregando modelo Whisper '{model_size}' ({device['label']})...")
        self.model = WhisperModel(model_size, **kwargs)
        # Viés de vocabulário (ver dictionary.py) — None até o Worker
        # reaplicar o dicionário atual logo depois de criar este objeto
        # (ver worker.load_models), já que um Transcriber novo nunca lembra
        # do que o anterior tinha.
        self.initial_prompt = None
        self._warmup()
        print("[GeniusPeach] Whisper carregado e pronto.")

    def set_initial_prompt(self, prompt):
        self.initial_prompt = prompt

    def _warmup(self):
        # Primeira inferência da sessão paga um custo fixo de inicialização
        # (alocação de memória na GPU, compilação de kernels). Roda isso
        # agora com meio segundo de silêncio, fora do primeiro ditado real.
        try:
            dummy_audio = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
            list(self.model.transcribe(dummy_audio, language="pt", beam_size=1))
        except Exception as e:
            print(f"[AVISO] Warm-up do Whisper falhou (sem impacto além do 1º ditado): {e}")

    def transcribe(self, audio_data):
        if audio_data is None or len(audio_data) == 0:
            return ""

        start = time.perf_counter()

        # no_speech_threshold: acima disso, o Whisper decide que o trecho
        # inteiro "não tem fala" e não emite NADA pra ele — silencioso, sem
        # erro. 0.4 (não 0.6) de propósito: cada chamada aqui já recebe um
        # trecho que o detector de pausa por RMS (audio_recorder.py) só
        # corta depois de confirmar fala de verdade — um limiar alto
        # some com fala baixa/curta bem no fim de um trecho, virando gaps
        # na transcrição.
        # vad_filter descarta trechos de silêncio antes de decodificar, então
        # pausas (ex: hesitação enquanto a tecla está pressionada) não custam
        # tempo de inferência.
        segments, _ = self.model.transcribe(
            audio_data,
            language="pt",
            beam_size=1,
            no_speech_threshold=0.4,
            log_prob_threshold=-1.0,
            condition_on_previous_text=False,
            vad_filter=WHISPER_VAD_FILTER,
            vad_parameters=dict(min_silence_duration_ms=WHISPER_VAD_MIN_SILENCE_MS),
            initial_prompt=self.initial_prompt,
        )

        text = " ".join([segment.text for segment in segments]).strip()

        elapsed = time.perf_counter() - start
        print(f"[GeniusPeach] Transcrição: {elapsed:.2f}s")

        # Filtra alucinações comuns de silêncio
        if text.lower() in HALLUCINATIONS:
            return ""

        return text