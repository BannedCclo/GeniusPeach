import time
import ollama
from config import (
    OLLAMA_MODEL,
    OLLAMA_KEEP_ALIVE,
    SYSTEM_PROMPT,
    OPTIMIZER_FIXED_RULES,
    DEFAULT_OUTPUT_LANGUAGE,
    output_language_instruction,
)

class TextOptimizer:
    def __init__(self, model=None):
        self.model = model or OLLAMA_MODEL
        self._warmup()

    def _warmup(self):
        # Força o Ollama a carregar o modelo agora (na inicialização do app)
        # em vez de na primeira transcrição, e já fixa o keep_alive pra ele
        # não ser descarregado da memória entre um ditado e outro.
        try:
            ollama.generate(
                model=self.model,
                prompt="Oi",
                options={"num_predict": 1},
                keep_alive=OLLAMA_KEEP_ALIVE,
            )
        except Exception as e:
            print(f"[AVISO] Warm-up do Ollama falhou (verifique se o Ollama está rodando): {e}")

    def optimize(self, text_raw, system_prompt=None, output_language=DEFAULT_OUTPUT_LANGUAGE):
        if not text_raw.strip():
            return ""

        start = time.perf_counter()

        rules = OPTIMIZER_FIXED_RULES
        # Instrução de idioma é OPCIONAL (None pro padrão "pt", ver
        # config.output_language_instruction) — some da mensagem inteira em
        # vez de aparecer vazia quando o usuário não mudou o padrão.
        lang_instruction = output_language_instruction(output_language)
        if lang_instruction:
            rules = f"{rules}\n- {lang_instruction}"

        response = ollama.generate(
            model=self.model,
            # OPTIMIZER_FIXED_RULES sempre entra, não importa qual perfil —
            # são regras de FORMATO da resposta (não responder à mensagem,
            # devolver só o texto), que não fazem sentido variar por perfil
            # e por isso não vivem dentro do prompt de cada um (ver config.py).
            prompt=f"{system_prompt or SYSTEM_PROMPT}\n\n{rules}\n\nTexto original: {text_raw}",
            options={
                "temperature": 0.1,
                # Um teto fixo baixo (100, valor antigo) cortava ditados
                # longos pela metade: a limpeza de vícios de linguagem
                # raramente ENCOLHE o texto o bastante pra compensar o que a
                # pontuação/formatação adiciona, então a saída corrigida
                # tende a ficar perto do tamanho da entrada, não muito menor.
                # Escala com o texto original (~3 chars/token em português,
                # com folga) em vez de travar tudo acima de ~75 palavras.
                "num_predict": max(256, len(text_raw) // 2),
            },
            keep_alive=OLLAMA_KEEP_ALIVE,
        )

        elapsed = time.perf_counter() - start
        print(f"[GeniusPeach] Otimização de texto: {elapsed:.2f}s")

        return response['response'].strip()
