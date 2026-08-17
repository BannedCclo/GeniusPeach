import time
import ollama
from config import OLLAMA_MODEL, OLLAMA_KEEP_ALIVE, SYSTEM_PROMPT

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

    def optimize(self, text_raw):
        if not text_raw.strip():
            return ""

        start = time.perf_counter()

        response = ollama.generate(
            model=self.model,
            prompt=f"{SYSTEM_PROMPT}\n\nTexto original: {text_raw}",
            options={
                "temperature": 0.1,
                "num_predict": 100
            },
            keep_alive=OLLAMA_KEEP_ALIVE,
        )

        elapsed = time.perf_counter() - start
        print(f"[GeniusPeach] Otimização de texto: {elapsed:.2f}s")

        return response['response'].strip()
