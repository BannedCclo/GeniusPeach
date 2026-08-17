import time
import numpy as np
import torch
from faster_whisper import WhisperModel
from config import (
    WHISPER_MODEL_SIZE,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
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
    def __init__(self, model_size=None):
        model_size = model_size or WHISPER_MODEL_SIZE

        print("[GeniusPeach] Verificando aceleração de hardware...")
        if not torch.cuda.is_available():
            print("[AVISO] CUDA não detectada! O modelo rodará na CPU (latência maior).")
        else:
            print(f"[GeniusPeach] GPU ativa: {torch.cuda.get_device_name(0)}")

        print(f"[GeniusPeach] Carregando modelo Whisper '{model_size}' na VRAM...")
        self.model = WhisperModel(
            model_size,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE
        )
        self._warmup()
        print("[GeniusPeach] Whisper carregado e pronto.")

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

        # no_speech_threshold=0.6 instrui o Whisper a descartar áudio com alta probabilidade de ser silêncio
        # vad_filter descarta trechos de silêncio antes de decodificar, então
        # pausas (ex: hesitação enquanto a tecla está pressionada) não custam
        # tempo de inferência.
        segments, _ = self.model.transcribe(
            audio_data,
            language="pt",
            beam_size=1,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            condition_on_previous_text=False,
            vad_filter=WHISPER_VAD_FILTER,
            vad_parameters=dict(min_silence_duration_ms=WHISPER_VAD_MIN_SILENCE_MS),
        )

        text = " ".join([segment.text for segment in segments]).strip()

        elapsed = time.perf_counter() - start
        print(f"[GeniusPeach] Transcrição: {elapsed:.2f}s")

        # Filtra alucinações comuns de silêncio
        if text.lower() in HALLUCINATIONS:
            return ""

        return text