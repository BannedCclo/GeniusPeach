import sounddevice as sd
import numpy as np
from config import (
    SAMPLE_RATE,
    CHANNELS,
    LIVE_CHUNK_SILENCE_MS,
    LIVE_CHUNK_MIN_SPEECH_MS,
    LIVE_CHUNK_RMS_THRESHOLD,
)


class AudioRecorder:
    def __init__(self, level_callback=None, chunk_callback=None):
        self.recording = False
        self.stream = None
        # Chamado a cada bloco de áudio com um nível 0..1 (RMS), pra UI
        # poder mostrar um medidor reagindo à voz em tempo real.
        self.level_callback = level_callback
        # Chamado com cada TRECHO de áudio (numpy array) assim que uma
        # pausa é detectada durante a gravação — ditado ao vivo, ver
        # worker.process_chunk. A gravação continua rodando; só o
        # acumulador de trecho é reiniciado.
        self.chunk_callback = chunk_callback

        self._chunk_frames = []
        self._speech_ms = 0.0        # só a duração classificada como fala
        self._silence_ms = 0.0       # silêncio contínuo desde a última fala
        self._silence_frame_count = 0  # em amostras, pra saber quanto cortar
        self._had_speech = False

    def start(self):
        self.recording = True
        self._chunk_frames = []
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._silence_frame_count = 0
        self._had_speech = False

        def callback(indata, frames, time_info, status):
            if not self.recording:
                return

            block = indata.copy()
            block_ms = frames / SAMPLE_RATE * 1000.0
            rms = float(np.sqrt(np.mean(np.square(block))))

            if self.level_callback is not None:
                self.level_callback(min(1.0, rms * 5.0))

            self._chunk_frames.append(block)

            if rms >= LIVE_CHUNK_RMS_THRESHOLD:
                self._had_speech = True
                self._speech_ms += block_ms
                self._silence_ms = 0.0
                self._silence_frame_count = 0
            else:
                self._silence_ms += block_ms
                self._silence_frame_count += frames
                if (
                    self._had_speech
                    and self._silence_ms >= LIVE_CHUNK_SILENCE_MS
                    and self._speech_ms >= LIVE_CHUNK_MIN_SPEECH_MS
                ):
                    self._cut_chunk()

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            callback=callback,
            dtype='float32'
        )
        self.stream.start()

    def _cut_chunk(self):
        if not self._chunk_frames:
            return
        audio = np.concatenate(self._chunk_frames, axis=0).flatten()
        if self._silence_frame_count > 0:
            # Não manda o rabo de silêncio que confirmou a pausa — só a
            # fala de verdade, mais compacto pro Whisper transcrever.
            audio = audio[: max(0, len(audio) - self._silence_frame_count)]

        self._chunk_frames = []
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._silence_frame_count = 0
        self._had_speech = False

        if audio.size > 0 and self.chunk_callback is not None:
            self.chunk_callback(audio)

    def stop(self):
        self.recording = False
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        # Qualquer fala ainda não fechada por uma pausa (ex.: o usuário
        # soltou a tecla bem no meio de uma frase) vira o último trecho —
        # sem isso, a cauda do ditado se perderia.
        self._cut_chunk()
