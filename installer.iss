; Script do Inno Setup para o instalador do GeniusPeach — gera um único
; GeniusPeach-Setup.exe a partir do build do PyInstaller (onedir).
;
; Build CPU-only de propósito (ver requirements-cpu.txt e o README): o
; build CUDA (venv/requirements.txt) pesa ~5,3GB por causa das DLLs de
; runtime do PyTorch/CUDA, o que estoura o limite de anexo do GitHub
; Releases e é um download desnecessário pra quem não tem GPU NVIDIA.
; Quem quiser aceleração por GPU roda a partir do código-fonte (ver README).
;
; Como gerar:
;   1. venv-build-cpu\Scripts\python.exe -m PyInstaller GeniusPeach.spec ^
;        --distpath dist-cpu --workpath build-cpu --noconfirm --clean
;   2. ISCC.exe installer.iss
; O .exe final sai em installer_output\GeniusPeach-Setup.exe

#define MyAppName "GeniusPeach"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "GeniusPeach"
#define MyAppURL "https://github.com/BannedCclo/GeniusPeach"
#define MyAppExeName "GeniusPeach.exe"

[Setup]
AppId={{9C6D7A7C-3F2B-4B7C-9E7D-2C7F6F3D9A11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Instalador de usuário único (não precisa de admin) — evita prompt de UAC
; pra quem só quer testar o app rapidamente.
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=GeniusPeach-Setup
SetupIconFile=icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um ícone na área de trabalho"; GroupDescription: "Ícones adicionais:"

[Files]
; dist-cpu\GeniusPeach\ é a saída do PyInstaller (onedir) — todo o
; conteúdo (exe + _internal\) entra no instalador.
Source: "dist-cpu\GeniusPeach\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

; Configurações locais do usuário (settings.json, perfis, dicionário, em
; %APPDATA%\GeniusPeach) ficam FORA de {app} de propósito e não são
; tocadas por desinstalar/reinstalar — preserva a config entre versões.
