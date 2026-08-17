import pyperclip
import pyautogui
import time

def inject_text(text):
    if not text:
        return
    
    # Copia o texto otimizado para a área de transferência
    pyperclip.copy(text)
    
    # Cola no campo ativo do sistema
    time.sleep(0.05)
    pyautogui.hotkey('ctrl', 'v')