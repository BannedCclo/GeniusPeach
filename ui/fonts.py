# Carrega como "fontes de aplicação" (não precisam estar instaladas no
# Windows do usuário) as fontes reais do design system "Tactile Peach":
# Hanken Grotesk (corpo/títulos) e Material Symbols Outlined (o pacote de
# ícones que o Stitch usa via ligadura de nome, ex. "mic" -> glifo de
# microfone). Chame `load_fonts()` uma vez, logo após criar a QApplication
# e antes de construir qualquer widget.

import os

from PySide6.QtGui import QFontDatabase

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

_FILES = [
    "HankenGrotesk-Regular.ttf",
    "HankenGrotesk-Medium.ttf",
    "HankenGrotesk-SemiBold.ttf",
    "HankenGrotesk-Bold.ttf",
    "MaterialSymbolsOutlined.ttf",
]

_loaded = False


def load_fonts():
    global _loaded
    if _loaded:
        return
    for filename in _FILES:
        path = os.path.join(ASSETS_DIR, filename)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
        else:
            print(f"[GeniusPeach] Fonte não encontrada em assets/: {filename}")
    _loaded = True
