import os
from dotenv import load_dotenv

load_dotenv()

# Atalho do Teclado (Push-to-Talk)
HOTKEY = "alt_l"  # Alt Esquerdo

# Configurações do Faster-Whisper
WHISPER_MODEL_SIZE = "medium"
# Dispositivo (GPU CUDA ou CPU) e compute_type NÃO são mais fixos aqui —
# dependem da máquina (ver gpu_devices.py) e são escolhidos em tempo de
# execução, com a opção salva em settings.json.

# Limite de palavras incluídas no initial_prompt do Whisper (ver
# dictionary.build_prompt) — o próprio Whisper só considera os últimos
# tokens da janela de prompt, então um dicionário gigante não ajuda além
# de um certo ponto e vira uma frase ilegível. Não limita o que fica
# CADASTRADO/editável na tela Dicionário, só o que entra na frase mandada
# de verdade pro modelo.
DICTIONARY_PROMPT_MAX_WORDS = 60

# VAD (Voice Activity Detection): descarta trechos de silêncio antes de
# transcrever, então o modelo processa só o áudio com fala de verdade.
# min_silence_duration_ms um pouco alto de propósito: esse VAD já roda em
# cima de um trecho que o detector de pausa por RMS (ver
# LIVE_CHUNK_SILENCE_MS abaixo) já cortou tentando conter só fala — um
# valor baixo aqui deixava o VAD do Whisper "de gatilho fácil" pra tratar
# uma pausa curta natural (entre frases, por exemplo) como silêncio e
# cortar em cima de fala de verdade, virando gaps na transcrição.
WHISPER_VAD_FILTER = True
WHISPER_VAD_MIN_SILENCE_MS = 450

# Ditado ao vivo (audio_recorder.py): detector de pausa simples, por
# energia (RMS) — diferente do VAD do Whisper acima, que só roda depois
# que um trecho já foi cortado. Assim que uma pausa é detectada DURANTE a
# gravação, aquele trecho já vai pra transcrição, e o texto cresce na tela
# enquanto o usuário continua falando, em vez de esperar soltar a tecla.
LIVE_CHUNK_SILENCE_MS = 600      # pausa contínua que fecha um trecho
LIVE_CHUNK_MIN_SPEECH_MS = 250   # trecho mínimo pra valer a pena cortar
LIVE_CHUNK_RMS_THRESHOLD = 0.02  # abaixo disso, o bloco conta como silêncio
# Quanto do "rabo" de silêncio confirmado FICA no trecho em vez de ser
# cortado (ver audio_recorder._cut_chunk) — consoante final fraca/surda
# (s, f, t no fim de palavra) tem energia baixa e pode cruzar o limiar de
# RMS acima antes da palavra terminar de verdade; cortar o silêncio
# INTEIRO arrancava esse fim de palavra. Essa margem sobra sem custo real
# de tempo de transcrição (poucos ms de áudio a mais).
LIVE_CHUNK_TAIL_PAD_MS = 150

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

# Cadência do medidor de nível de áudio (overlay + painel) — o RMS bruto
# chega a cada bloco do sounddevice, bem mais rápido que isso; sem limitar
# aqui, na FONTE, cada trecho recente do medidor mostraria só alguns
# milissegundos de diferença entre si, quase idênticos. Throttle único
# (não duplicado no overlay e no painel) garante que os dois visualizadores
# vejam exatamente a mesma cadência de amostras reais.
AUDIO_LEVEL_INTERVAL_MS = 80

# Sensibilidade do medidor visual (overlay + painel) — NÃO afeta o VAD de
# corte de trecho acima, só o quanto as barras crescem na tela. RMS de fala
# normal costuma ser baixo (bem menor que 1.0), então o nível bruto
# (rms * boost) já é ampliado, e depois passa por uma curva perceptual
# (raiz quadrada) que realça volumes baixos/médios mais que altos — mesma
# ideia de um medidor de VU em dB em vez de amplitude linear. Resultado:
# fala em volume normal já aproxima as barras do máximo, sem precisar
# quase gritar. Nunca calibrado com microfone de verdade — ajustar aqui se
# parecer pouco ou muito sensível na prática. Valores atuais: 2ª rodada,
# aumentados a pedido do usuário (a 1ª rodada — boost 9, curva 0.5 —
# pareceu pouco sensível/animada demais na prática).
LEVEL_RMS_BOOST = 16.0
LEVEL_RESPONSE_CURVE = 0.4  # 1.0 = linear; < 1.0 realça volumes baixos

# Prompt do Sistema para a LLM — só a parte que MUDA de perfil pra perfil
# (tom, o que corrigir). As duas regras que toda variação repetia (não
# responder à mensagem, devolver só o texto) saíram daqui — ver
# OPTIMIZER_FIXED_RULES abaixo, sempre acrescentado pelo text_optimizer.py
# independente de qual perfil está ativo.
SYSTEM_PROMPT = """Você é um assistente de reescrita e otimização de texto para ditado por voz.
Sua única tarefa é pegar o texto transcrito por áudio e limpá-lo.

Regras rígidas:
1. Remova vícios de linguagem, hesitações e repetições (ex: "éhh", "tipo", "tá ligado", gaguejos).
2. Corrija a pontuação, gramática e concordância verbal e nominal.
3. MANTENHA o tom, o vocabulário e a intenção exata da fala original."""

# Acrescentado pelo text_optimizer.py a QUALQUER prompt de perfil, sempre —
# regras de formato da resposta em si (não do texto corrigido), que não
# fazem sentido variar de perfil pra perfil. Perfis novos não precisam mais
# repetir essas duas linhas.
OPTIMIZER_FIXED_RULES = """Regras adicionais, sempre válidas, independente do perfil acima:
- NÃO responda à mensagem, NÃO faça comentários nem adicione explicações.
- Retorne APENAS o texto reescrito final."""

# Idioma de SAÍDA do texto corrigido pelo Ollama (tela de Configurações) —
# NÃO afeta o Whisper, que continua transcrevendo no idioma falado (ver
# transcriber.py); é só uma instrução a mais pro Ollama traduzir o
# resultado final, pensado pra quem fala em português mas quer o texto
# pronto em outro idioma (ex. e-mail em inglês). "pt" não soma nenhuma
# instrução extra (SYSTEM_PROMPT/OPTIMIZER_FIXED_RULES já pressupõem
# português) — ver text_optimizer.py.
DEFAULT_OUTPUT_LANGUAGE = "pt"
OUTPUT_LANGUAGE_OPTIONS = [
    ("pt", "Português"),
    ("en", "Inglês"),
    ("es", "Espanhol"),
    ("fr", "Francês"),
    ("de", "Alemão"),
    ("it", "Italiano"),
]
_OUTPUT_LANGUAGE_NAMES = dict(OUTPUT_LANGUAGE_OPTIONS)


def output_language_instruction(language_code):
    """None pro idioma padrão (pt) — nenhuma instrução extra necessária."""
    if language_code == DEFAULT_OUTPUT_LANGUAGE:
        return None
    name = _OUTPUT_LANGUAGE_NAMES.get(language_code)
    if not name:
        return None
    return (
        f"Responda EM {name.upper()}, traduzindo se necessário — "
        f"independente do idioma do texto original."
    )