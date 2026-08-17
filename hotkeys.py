"""Representação e rotulagem de atalhos — qualquer tecla física ou
combinação, capturada ao vivo na tela de Configurações (ui/web/app.js) e
comparada aqui contra os eventos reais do pynput (main.py).

Cada tecla física vira um id canônico, no MESMO esquema usado por
ui/web/app.js — os dois lados nunca precisam se traduzir um pro outro:
  - teclas que o pynput já expõe como enum nomeado (modificadores, F1-F24,
    setas, Caps Lock etc.) usam o próprio `Key.name`.
  - teclas de letra/número/pontuação usam o virtual-key code do Windows
    (ex.: "vk80" pra "P") — não muda com Shift/CapsLock, ao contrário do
    caractere digitado.

Um atalho é uma lista desses ids: todos precisam estar pressionados ao
mesmo tempo (ver main.py). Sem trava nenhuma sobre o que pode ser
escolhido — inclusive uma tecla comum sozinha, sem modificador (decisão
explícita do usuário: liberdade total, mesmo sabendo que isso sequestra
aquela tecla da digitação normal em qualquer app).

Pegadinha da plataforma: o hook de teclado do Windows (e por extensão o
pynput) só distingue esquerda/direita de verdade para Ctrl e Alt. Shift e a
tecla Win NÃO têm essa distinção — pressionar o lado ESQUERDO delas chega
como o nome genérico ("shift", "cmd"), só o lado DIREITO tem identidade
própria ("shift_r", "cmd_r"). Por isso não existe "shift_l"/"cmd_l" aqui;
usar esses ids faria a combinação nunca bater com uma pressionada de
verdade. `id_for_pynput_key` já devolve exatamente essa forma."""

from pynput import keyboard

DEFAULT_HOTKEY = ["alt_l"]

# Ordem de exibição: modificadores antes da tecla principal, sempre no
# mesmo lugar não importa a ordem em que o usuário apertou ao capturar.
_MODIFIER_PRIORITY = {
    "ctrl_l": 0, "ctrl_r": 1,
    "alt_l": 2, "alt_r": 3, "alt_gr": 4,
    "shift": 5, "shift_r": 6,
    "cmd": 7, "cmd_r": 8,
}

_NAMED_LABELS = {
    "ctrl_l": "Ctrl esquerdo", "ctrl_r": "Ctrl direito",
    "alt_l": "Alt esquerdo", "alt_r": "Alt direito", "alt_gr": "Alt Gr",
    "shift": "Shift esquerdo", "shift_r": "Shift direito",
    "cmd": "Win esquerda", "cmd_r": "Win direita",
    "esc": "Esc", "tab": "Tab", "space": "Espaço", "enter": "Enter",
    "backspace": "Backspace", "delete": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "page_up": "Page Up", "page_down": "Page Down",
    "up": "↑", "down": "↓", "left": "←", "right": "→",
    "caps_lock": "Caps Lock", "num_lock": "Num Lock", "scroll_lock": "Scroll Lock",
    "print_screen": "Print Screen", "pause": "Pause", "menu": "Menu",
}
for _n in range(1, 25):
    _NAMED_LABELS[f"f{_n}"] = f"F{_n}"

# vk<código> -> rótulo, pra letras, números e a pontuação mais comum
# (mesmos códigos do Win32 VK_*, o que ui/web/app.js também usa).
_VK_LABELS = {}
for _code in range(ord("A"), ord("Z") + 1):
    _VK_LABELS[f"vk{_code}"] = chr(_code)
for _code in range(ord("0"), ord("9") + 1):
    _VK_LABELS[f"vk{_code}"] = chr(_code)
_VK_LABELS.update({
    "vk189": "-", "vk187": "=", "vk219": "[", "vk221": "]", "vk220": "\\",
    "vk186": ";", "vk222": "'", "vk188": ",", "vk190": ".", "vk191": "/",
    "vk192": "`",
})


def label_for_id(key_id):
    return _NAMED_LABELS.get(key_id) or _VK_LABELS.get(key_id) or key_id


def canonical_order(key_ids):
    return sorted(key_ids, key=lambda k: (_MODIFIER_PRIORITY.get(k, 100), k))


def label_for(key_ids):
    if not key_ids:
        return ""
    return " + ".join(label_for_id(k) for k in canonical_order(key_ids))


def id_for_pynput_key(key):
    """Traduz um objeto do pynput (Key ou KeyCode, como chega em
    on_press/on_release) pro mesmo esquema de ids usado na captura via
    navegador. None pra teclas sem equivalente reconhecido — essas não
    podem fazer parte de um atalho."""
    if isinstance(key, keyboard.KeyCode):
        if key.vk is not None:
            return f"vk{key.vk}"
        return None
    if isinstance(key, keyboard.Key):
        return key.name
    return None
