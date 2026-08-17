import os
from dotenv import load_dotenv

load_dotenv()

# Atalho do Teclado (Push-to-Talk)
HOTKEY = "alt_l"  # Alt Esquerdo

# Configurações do Faster-Whisper
WHISPER_MODEL_SIZE = "medium"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE_TYPE = "float16"  # Otimizado para RTX 3060 Ti (~2-3 GB VRAM)

# VAD (Voice Activity Detection): descarta trechos de silêncio antes de
# transcrever, então o modelo processa só o áudio com fala de verdade.
WHISPER_VAD_FILTER = True
WHISPER_VAD_MIN_SILENCE_MS = 300

# Ditado ao vivo (audio_recorder.py): detector de pausa simples, por
# energia (RMS) — diferente do VAD do Whisper acima, que só roda depois
# que um trecho já foi cortado. Assim que uma pausa é detectada DURANTE a
# gravação, aquele trecho já vai pra transcrição, e o texto cresce na tela
# enquanto o usuário continua falando, em vez de esperar soltar a tecla.
LIVE_CHUNK_SILENCE_MS = 600      # pausa contínua que fecha um trecho
LIVE_CHUNK_MIN_SPEECH_MS = 250   # trecho mínimo pra valer a pena cortar
LIVE_CHUNK_RMS_THRESHOLD = 0.02  # abaixo disso, o bloco conta como silêncio

# Configurações do Ollama (Qwen 2.5 3B)
OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_HOST = "http://localhost:11434"
# Mantém o modelo carregado na memória entre um ditado e outro — sem isso, o
# Ollama descarrega o modelo após 5 min parado (padrão dele) e a próxima
# chamada paga o custo de recarregar do zero antes de gerar qualquer token.
OLLAMA_KEEP_ALIVE = "30m"

# Configurações de Áudio
SAMPLE_RATE = 16000
CHANNELS = 1

# Prompt do Sistema para a LLM
SYSTEM_PROMPT = """Você é um assistente de reescrita e otimização de texto para ditado por voz.
Sua única tarefa é pegar o texto transcrito por áudio e limpá-lo.

Regras rígidas:
1. Remova vícios de linguagem, hesitações e repetições (ex: "éhh", "tipo", "tá ligado", gaguejos).
2. Corrija a pontuação, gramática e concordância verbal e nominal.
3. MANTENHA o tom, o vocabulário e a intenção exata da fala original.
4. NÃO responda à mensagem, NÃO faça comentários nem adicione explicações.
5. Retorne APENAS o texto corrigido final."""