# GeniusPeach

Ditado por voz local para Windows: transcreve o que você fala com
**faster-whisper** (Whisper rodando localmente, sem enviar áudio pra
nenhum servidor) e usa uma LLM local via **Ollama** pra limpar o texto —
remover vícios de linguagem, corrigir pontuação e gramática — antes de
colar automaticamente onde o cursor estiver. Tudo roda na sua máquina.

## Recursos

- **Ditado global por atalho**: segure a tecla pra gravar (hold-to-talk)
  ou dê um duplo clique pra ligar/desligar (toggle) — funciona em
  qualquer app, painel aberto ou fechado. Atalho totalmente configurável.
- **Correção por IA com perfis**: cada perfil é um prompt diferente pro
  Ollama (ex.: um tom pra e-mails formais, outro que traduz descrições
  leigas em termos técnicos de engenharia de software). Troque de perfil
  pela tela ou por um segundo atalho global configurável, que mostra um
  aviso flutuante na tela com o perfil ativo.
- **Dicionário de vocabulário**: cadastre palavras que você fala com
  frequência (nomes, termos técnicos, jargão) pra enviesar o Whisper a
  reconhecê-las certo. Dá pra corrigir uma transcrição direto no
  histórico e a IA sugere adicionar as palavras diferentes ao dicionário.
- **Histórico** com o texto bruto (Whisper) e o texto corrigido (Ollama)
  lado a lado, com cópia e correção de cada ditado.
- **Idioma de saída configurável**: dita em português, mas quer o texto
  final em inglês? A correção final pode sair em outro idioma sem mudar
  o idioma da transcrição.
- **Microfone e dispositivo de processamento (GPU/CPU) configuráveis**,
  com detecção automática do hardware disponível.
- **Painel neumórfico** (Configurações, Perfis, Dicionário, Histórico) e
  overlay flutuante discreto durante a gravação.

## Pré-requisitos (em qualquer forma de instalação)

- Windows 10/11 de 64 bits.
- **[Ollama](https://ollama.com/download)** instalado e rodando
  localmente — é quem faz a correção do texto. Depois de instalar, baixe
  o modelo padrão do GeniusPeach:
  ```
  ollama pull qwen2.5:3b
  ```
  (dá pra trocar o modelo depois, pela tela de Configurações do próprio
  app — qualquer modelo instalado no Ollama aparece lá.)

## Instalação rápida (recomendada para a maioria)

1. Baixe o instalador na [página de
   Releases](https://github.com/BannedCclo/GeniusPeach/releases/latest)
   (`GeniusPeach-Setup.exe`).
2. Rode o instalador e siga o assistente (não precisa de privilégios de
   administrador).
3. Garanta que o Ollama está rodando (ícone dele na bandeja, ou
   `ollama serve`) e que já baixou o modelo (`ollama pull qwen2.5:3b`).
4. Abra o GeniusPeach pelo atalho criado — ele fica na bandeja do
   sistema. Segure **Alt esquerdo** (padrão, configurável) em qualquer
   lugar pra ditar.

Esse instalador roda em **qualquer PC Windows**, mas a transcrição usa só
CPU (sem aceleração por GPU) — pra manter o download pequeno o bastante
pra caber num Release do GitHub. Continua rápido o bastante pro uso do
dia a dia com os modelos `tiny`/`base`/`small`; modelos maiores
(`medium`, `large-v3`) ficam mais lentos sem GPU.

## Instalação com aceleração por GPU (NVIDIA/CUDA)

Se você tem uma GPU NVIDIA e quer usar modelos maiores/mais precisos do
Whisper com velocidade de GPU, rode a partir do código-fonte — o pacote
de GPU do PyTorch é grande demais (~5GB) pra distribuir como instalador
pronto.

Pré-requisitos adicionais:
- [Python 3.13](https://www.python.org/downloads/) (64 bits).
- [Git](https://git-scm.com/downloads).
- GPU NVIDIA com driver atualizado (CUDA vem embutido no pacote do
  PyTorch, não precisa instalar o CUDA Toolkit separado).

```powershell
git clone https://github.com/BannedCclo/GeniusPeach.git
cd GeniusPeach
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py
```

Na tela de Configurações, escolha sua GPU em "Dispositivo de
processamento" (aparece automaticamente quando detectada).

### Gerar seu próprio instalador (setup.exe)

O repositório já traz tudo que o instalador CPU-only precisa
(`requirements-cpu.txt`, `GeniusPeach.spec`, `installer.iss`). Requer o
[Inno Setup 6](https://jrsoftware.org/isinfo.php) instalado
(`winget install JRSoftware.InnoSetup`).

```powershell
python -m venv venv-build-cpu
venv-build-cpu\Scripts\pip install -r requirements-cpu.txt pyinstaller
venv-build-cpu\Scripts\python -m PyInstaller GeniusPeach.spec --distpath dist-cpu --workpath build-cpu --noconfirm --clean
"C:\Users\<você>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

O instalador final sai em `installer_output\GeniusPeach-Setup.exe`. Pra
gerar a versão com CUDA (bem maior), troque `requirements-cpu.txt` por
`requirements.txt` e o `--distpath`/`--workpath` por pastas diferentes de
`dist-cpu`/`build-cpu` (ex. `dist`/`build`, os padrões).

## Como usar

- **Segurar o atalho de ditado** (padrão: Alt esquerdo) grava enquanto
  está pressionado; soltar encerra e injeta o texto corrigido onde o
  cursor estiver.
- **Duplo clique** no mesmo atalho liga o modo contínuo (toggle); duplo
  clique de novo desliga.
- **Atalho de ciclar perfis** (padrão: Ctrl+Shift+P) avança pro próximo
  perfil de correção, mesmo com o painel fechado — um aviso flutuante
  mostra qual ficou ativo.
- O ícone na **bandeja do sistema** abre o painel (Configurações,
  Perfis, Dicionário, Histórico) ou encerra o app.

Todos os atalhos, o modelo do Whisper/Ollama, o microfone, o dispositivo
de processamento e o idioma de saída são configuráveis na aba
Configurações do painel.

## Estrutura do projeto

```
main.py              ponto de entrada — hotkeys globais, wiring geral
worker.py             pipeline de transcrição (Whisper) + correção (Ollama)
transcriber.py         wrapper do faster-whisper
text_optimizer.py       chamada ao Ollama
audio_recorder.py       captura de áudio + detecção de pausas
injector.py            cola o texto final onde o cursor estiver
profiles.py / dictionary.py / settings.py   persistência em %APPDATA%\GeniusPeach
ui/webdashboard.py      painel (QWebEngineView) + ponte Python↔JS
ui/web/                HTML/CSS/JS do painel
ui/overlay.py / profile_toast.py   janelas flutuantes nativas
GeniusPeach.spec        build do PyInstaller
installer.iss           script do instalador (Inno Setup)
```
