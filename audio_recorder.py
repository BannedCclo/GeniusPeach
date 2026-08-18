import time

import sounddevice as sd
import numpy as np
from config import (
    SAMPLE_RATE,
    CHANNELS,
    LIVE_CHUNK_SILENCE_MS,
    LIVE_CHUNK_MIN_SPEECH_MS,
    LIVE_CHUNK_RMS_THRESHOLD,
    LIVE_CHUNK_TAIL_PAD_MS,
    AUDIO_LEVEL_INTERVAL_MS,
    LEVEL_RMS_BOOST,
    LEVEL_RESPONSE_CURVE,
)

_TAIL_PAD_FRAMES = int(LIVE_CHUNK_TAIL_PAD_MS / 1000 * SAMPLE_RATE)


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

        # Microfone escolhido (índice do sounddevice) — None = dispositivo
        # padrão do sistema. Setado via set_device (ver audio_devices.py);
        # lido/escrito de threads diferentes (pynput, Bridge/GUI), mas é só
        # atribuição simples de int/None, o GIL garante atomicidade — mesmo
        # padrão já usado em self.recording/self.session_token.
        self._device = None

        self._chunk_frames = []
        self._speech_ms = 0.0        # só a duração classificada como fala
        self._silence_ms = 0.0       # silêncio contínuo desde a última fala
        self._silence_frame_count = 0  # em amostras, pra saber quanto cortar
        self._had_speech = False
        self._last_level_emit = 0.0
        # Identifica a gravação atual — incrementado em start(), ANTES do
        # áudio começar a fluir (o stream só começa a chamar `callback` DEPOIS
        # que este método já rodou até o fim). Cada trecho carrega esse
        # número consigo; quem decide se ele pertence à sessão "atual" é
        # quem recebe (Worker), comparando o número — em vez de depender de
        # um sinal separado de "começou" chegar numa ordem específica
        # relativa aos trechos, o que NÃO é garantido: trechos vêm da
        # thread interna do PortAudio, um sinal de início viria de
        # main.py/pynput — threads diferentes, sem ordem relativa
        # garantida entre elas numa fila do Qt.
        self.session_token = 0

    def start(self):
        self.recording = True
        self.session_token += 1
        self._chunk_frames = []
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._silence_frame_count = 0
        self._had_speech = False
        self._last_level_emit = 0.0

        def callback(indata, frames, time_info, status):
            if not self.recording:
                return

            block = indata.copy()
            block_ms = frames / SAMPLE_RATE * 1000.0
            rms = float(np.sqrt(np.mean(np.square(block))))

            if self.level_callback is not None:
                # Throttle na fonte (não em cada consumidor): o RMS bruto
                # chega a cada bloco (poucos ms), rápido demais pra virar
                # amostras distintas e legíveis num medidor de barras.
                now = time.monotonic()
                if (now - self._last_level_emit) * 1000.0 >= AUDIO_LEVEL_INTERVAL_MS:
                    self._last_level_emit = now
                    # Curva perceptual (raiz por padrão) depois do boost:
                    # realça volume baixo/médio mais que alto, então fala
                    # normal já aproxima o medidor do máximo — ver
                    # config.LEVEL_RESPONSE_CURVE.
                    raw = min(1.0, rms * LEVEL_RMS_BOOST)
                    self.level_callback(raw ** LEVEL_RESPONSE_CURVE)

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
            dtype='float32',
            device=self._device,
        )
        self.stream.start()

    def set_device(self, device_id):
        """device_id vem do seletor de Configurações (ver audio_devices.py):
        None ou "default" = deixa o sounddevice escolher; senão o índice do
        dispositivo como string. Só atualiza o atributo lido na PRÓXIMA
        start() — trocar de microfone no meio de uma gravação em andamento
        não a interrompe nem a afeta, só a gravação seguinte usa o novo."""
        self._device = None if device_id in (None, "default") else int(device_id)

    def _cut_chunk(self):
        if not self._chunk_frames:
            print(f"[GeniusPeach][diag] _cut_chunk(token={self.session_token}): "
                  f"sem frames acumulados, nada a cortar.")
            return
        n_frames = len(self._chunk_frames)
        audio = np.concatenate(self._chunk_frames, axis=0).flatten()
        raw_len = len(audio)
        # Só apara o "rabo" de silêncio se JÁ HOUVE fala confirmada — sem
        # isso, se o RMS nunca cruzou LIVE_CHUNK_RMS_THRESHOLD durante a
        # gravação inteira (limiar não calibrado com microfone real; pode
        # estar alto demais pra esse microfone específico),
        # _silence_frame_count acumula desde o 1º bloco e vira igual ao
        # tamanho TOTAL do buffer — o corte abaixo apagaria a gravação
        # inteira, mesmo que a pessoa tenha falado o tempo todo. Bug real,
        # não relacionado a threads: "cortar o silêncio depois da fala" não
        # faz sentido se não houve fala confirmada pra cortar depois dela.
        trimmed = 0
        if self._had_speech and self._silence_frame_count > 0:
            # Não manda o grosso do silêncio que confirmou a pausa — mas
            # deixa uma margem de segurança (LIVE_CHUNK_TAIL_PAD_MS) em vez
            # de cortar o silêncio detectado por INTEIRO: uma consoante
            # final fraca/surda pode ter cruzado o limiar de RMS um
            # pouco antes da palavra terminar de verdade, e cortar tudo
            # arrancava esse fim de palavra — via como gap na transcrição.
            trimmed = max(0, self._silence_frame_count - _TAIL_PAD_FRAMES)
            audio = audio[: max(0, len(audio) - trimmed)]

        print(f"[GeniusPeach][diag] _cut_chunk(token={self.session_token}): "
              f"{n_frames} blocos, {raw_len} amostras brutas, "
              f"{trimmed} cortadas de silêncio"
              f"{'' if self._had_speech else ' (nenhuma — RMS nunca cruzou o limiar nesta gravação)'}, "
              f"{audio.size} amostras finais "
              f"({audio.size / SAMPLE_RATE:.2f}s).")

        self._chunk_frames = []
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._silence_frame_count = 0
        self._had_speech = False

        if audio.size > 0 and self.chunk_callback is not None:
            self.chunk_callback(audio, self.session_token)
        elif audio.size == 0:
            print("[GeniusPeach][diag] trecho descartado: 0 amostras depois do corte de silêncio "
                  "(a fala inteira foi tratada como cauda de silêncio?).")

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
