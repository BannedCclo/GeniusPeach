// Ponte entre o estado Qt (Python) e o DOM do painel.
// O Python nunca manipula o DOM direto: emite sinais no `bridge`, e cada
// handler daqui traduz isso pra classe/texto. Do lado inverso, os botões
// chamam slots do `bridge` (salvar, encerrar).

// Classes de navegação copiadas literalmente do mockup do Stitch — o item
// ativo é um poço afundado (neu-inset), o inativo é chapado com hover.
const NAV_ACTIVE = "text-primary font-bold neu-inset rounded-xl bg-surface-container-low flex items-center gap-4 px-4 py-3 cursor-pointer";
const NAV_IDLE = "text-on-surface-variant hover:bg-surface-container-highest rounded-xl transition-colors flex items-center gap-4 px-4 py-3 cursor-pointer";

let bridge = null;
let dirty = false;          // há alteração não salva nas configurações?
let recStart = null;        // início do ditado atual (para o cronômetro)
let recTimer = null;

// ---------------------------------------------------------------- navegação

function showView(name) {
  document.querySelectorAll(".view").forEach(function (v) {
    v.hidden = v.dataset.view !== name;
  });
  document.querySelectorAll(".nav-item").forEach(function (a) {
    const active = a.dataset.view === name;
    a.className = "nav-item " + (active ? NAV_ACTIVE : NAV_IDLE);
    const icon = a.querySelector(".material-symbols-outlined");
    icon.style.fontVariationSettings = active ? "'FILL' 1" : "";
  });
}

document.querySelectorAll(".nav-item").forEach(function (a) {
  a.addEventListener("click", function (e) {
    e.preventDefault();
    showView(a.dataset.view);
  });
});

// ------------------------------------------------------------------ estados

// Espelha o enum State do Python (app_state.py). O texto do cabeçalho e o
// comportamento do visualizador saem daqui. Note que NÃO há campo de ícone
// aqui — o botão de microfone é tratado à parte (setMicButtonRecording),
// porque ele só pode mostrar mic ou quadrado, nunca um glifo por estado.
const STATE_UI = {
  LOADING:      { title: "Carregando modelos…", sub: "Aguarde — Whisper e Ollama estão subindo", live: false, wave: false },
  IDLE:         { title: "Pronto",              sub: "Clique no microfone ou segure a tecla de atalho", live: false, wave: false },
  LISTENING:    { title: "Ouvindo…",            sub: "Transcrevendo em tempo real",             live: true,  wave: true },
  TRANSCRIBING: { title: "Transcrevendo…",      sub: "Whisper está processando o áudio",        live: true,  wave: true },
  OPTIMIZING:   { title: "Corrigindo texto…",   sub: "Ollama está revisando a transcrição",     live: true,  wave: true },
  DONE:         { title: "Concluído",           sub: "Texto digitado na janela ativa",          live: false, wave: false },
  ERROR:        { title: "Erro",                sub: "Algo falhou durante o ditado",            live: false, wave: false },
};

let currentState = "LOADING";

// O único botão de gravação da tela: mic parado, quadrado enquanto grava.
// Nunca mostra nenhum outro glifo, mesmo em TRANSCRIBING/OPTIMIZING/DONE/
// ERROR — essa distinção fica só no título e no subtítulo acima.
function setMicButtonRecording(recording) {
  const glyph = document.getElementById("mic-glyph");
  glyph.textContent = recording ? "stop" : "mic";
  glyph.style.color = recording ? "#ba1a1a" : "rgb(255, 179, 138)";
  // O poço do microfone afunda enquanto está gravando de verdade — mesma
  // ideia do :active do neu-button no mockup.
  document.getElementById("mic-well").classList.toggle("neu-inset", recording);
}

function onState(name) {
  currentState = name;
  const ui = STATE_UI[name] || STATE_UI.IDLE;

  document.getElementById("rec-title").textContent = ui.title;
  document.getElementById("rec-subtitle").textContent = ui.sub;
  document.getElementById("live-dot").hidden = !ui.live;
  document.getElementById("wave").classList.toggle("wave-idle", !ui.wave);

  setMicButtonRecording(name === "LISTENING");

  if (name === "LISTENING") {
    document.getElementById("rec-content").hidden = true;
    document.getElementById("rec-empty").hidden = false;
    document.getElementById("rec-text").textContent = "";
    startTimer();
  } else if (name === "IDLE" || name === "DONE" || name === "ERROR") {
    stopTimer();
  }
}

function startTimer() {
  recStart = Date.now();
  stopTimer(true);
  recTimer = setInterval(function () {
    const s = Math.floor((Date.now() - recStart) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    document.getElementById("rec-time").textContent = mm + ":" + ss;
  }, 500);
}

function stopTimer(keepValue) {
  if (recTimer) { clearInterval(recTimer); recTimer = null; }
  if (!keepValue && recStart) {
    const s = Math.floor((Date.now() - recStart) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    document.getElementById("rec-time").textContent = mm + ":" + ss;
  }
}

// Chamado várias vezes por ditado agora — um por trecho transcrito ao vivo
// enquanto a gravação ainda acontece (ver worker.process_chunk), sempre com
// o texto ACUMULADO até ali, não só o trecho novo. Por isso basta substituir
// o conteúdo a cada chamada para o texto "crescer" na tela sozinho.
function showText(text, raw) {
  if (!text) return;
  document.getElementById("rec-empty").hidden = true;
  document.getElementById("rec-content").hidden = false;
  const el = document.getElementById("rec-text");
  el.textContent = text;
  // Texto cru do Whisper sai em itálico/apagado; o corrigido pelo Ollama
  // assume o peso normal — mesma convenção do overlay.
  el.style.fontStyle = raw ? "italic" : "normal";
  el.style.opacity = raw ? "0.6" : "1";
}

// O nível real do microfone modula a amplitude das barras. As barras têm a
// animação `bounce` do mockup rodando por baixo; aqui só escalamos o
// conjunto, para o visualizador reagir à voz em vez de ser decorativo.
function onAudioLevel(level) {
  const wave = document.getElementById("wave");
  const scale = 0.35 + Math.min(1, Math.max(0, level)) * 0.65;
  wave.style.setProperty("--wave-scale", scale);
  wave.querySelectorAll(".wave-bar").forEach(function (b) {
    b.style.transform = "scaleY(" + scale + ")";
  });
}

// --------------------------------------------------------------- atalho global

// Ids canônicos = MESMO esquema usado no lado Python (hotkeys.py), pra os
// dois lados nunca precisarem se traduzir um pro outro. Teclas que o
// pynput já expõe como enum nomeado (modificadores, F1-F24, setas etc.)
// usam esse nome; teclas de letra/número/pontuação usam o virtual-key code
// do Windows (não muda com Shift/CapsLock, ao contrário do caractere
// digitado). Só existe "shift"/"cmd" pro lado ESQUERDO (sem "_l") porque o
// hook de teclado do Windows não distingue esquerda/direita nessas duas —
// só Ctrl e Alt têm essa distinção de verdade (ver hotkeys.py).
const CODE_TO_ID = {
  ControlLeft: "ctrl_l", ControlRight: "ctrl_r",
  AltLeft: "alt_l", AltRight: "alt_r",
  ShiftLeft: "shift", ShiftRight: "shift_r",
  MetaLeft: "cmd", MetaRight: "cmd_r",
  Escape: "esc", Tab: "tab", Space: "space", Enter: "enter",
  Backspace: "backspace", Delete: "delete", Insert: "insert",
  Home: "home", End: "end", PageUp: "page_up", PageDown: "page_down",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
  CapsLock: "caps_lock", NumLock: "num_lock", ScrollLock: "scroll_lock",
  PrintScreen: "print_screen", Pause: "pause", ContextMenu: "menu",
  Minus: "vk189", Equal: "vk187", BracketLeft: "vk219", BracketRight: "vk221",
  Backslash: "vk220", Semicolon: "vk186", Quote: "vk222", Comma: "vk188",
  Period: "vk190", Slash: "vk191", Backquote: "vk192",
};
for (let i = 1; i <= 24; i++) CODE_TO_ID["F" + i] = "f" + i;
for (let c = 65; c <= 90; c++) CODE_TO_ID["Key" + String.fromCharCode(c)] = "vk" + c;
for (let d = 0; d <= 9; d++) CODE_TO_ID["Digit" + d] = "vk" + (48 + d);

const ID_LABELS = {
  ctrl_l: "Ctrl esquerdo", ctrl_r: "Ctrl direito",
  alt_l: "Alt esquerdo", alt_r: "Alt direito",
  shift: "Shift esquerdo", shift_r: "Shift direito",
  cmd: "Win esquerda", cmd_r: "Win direita",
  esc: "Esc", tab: "Tab", space: "Espaço", enter: "Enter",
  backspace: "Backspace", delete: "Delete", insert: "Insert",
  home: "Home", end: "End", page_up: "Page Up", page_down: "Page Down",
  up: "↑", down: "↓", left: "←", right: "→",
  caps_lock: "Caps Lock", num_lock: "Num Lock", scroll_lock: "Scroll Lock",
  print_screen: "Print Screen", pause: "Pause", menu: "Menu",
};
for (let i = 1; i <= 24; i++) ID_LABELS["f" + i] = "F" + i;
const VK_LABELS = {
  vk189: "-", vk187: "=", vk219: "[", vk221: "]", vk220: "\\",
  vk186: ";", vk222: "'", vk188: ",", vk190: ".", vk191: "/", vk192: "`",
};
for (let c = 65; c <= 90; c++) VK_LABELS["vk" + c] = String.fromCharCode(c);
for (let d = 0; d <= 9; d++) VK_LABELS["vk" + (48 + d)] = String(d);

const MODIFIER_PRIORITY = {
  ctrl_l: 0, ctrl_r: 1, alt_l: 2, alt_r: 3, shift: 4, shift_r: 5, cmd: 6, cmd_r: 7,
};

function labelForId(id) {
  return ID_LABELS[id] || VK_LABELS[id] || id;
}

function canonicalOrder(ids) {
  return Array.from(ids).sort(function (a, b) {
    const pa = a in MODIFIER_PRIORITY ? MODIFIER_PRIORITY[a] : 100;
    const pb = b in MODIFIER_PRIORITY ? MODIFIER_PRIORITY[b] : 100;
    return pa !== pb ? pa - pb : a.localeCompare(b);
  });
}

function labelForCombo(ids) {
  if (!ids || !ids.length) return "";
  return canonicalOrder(ids).map(labelForId).join(" + ");
}

let hotkeyIds = [];             // combinação salva atualmente
let capturingHotkey = false;
let heldDuringCapture = new Set();

function setupHotkeyCapture() {
  const input = document.getElementById("hotkey-input");

  function stopCapturing(commit) {
    capturingHotkey = false;
    input.classList.remove("ring-2", "ring-primary-container");
    if (commit && heldDuringCapture.size > 0) {
      hotkeyIds = Array.from(heldDuringCapture);
      dirty = true;
      setStatus("Alterações não salvas.");
    }
    input.value = labelForCombo(hotkeyIds);
    heldDuringCapture = new Set();
  }

  input.addEventListener("click", function () {
    if (capturingHotkey) return;
    capturingHotkey = true;
    heldDuringCapture = new Set();
    input.classList.add("ring-2", "ring-primary-container");
    input.value = "Pressione as teclas…";
  });

  input.addEventListener("blur", function () {
    if (capturingHotkey) stopCapturing(false);
  });

  window.addEventListener("keydown", function (e) {
    if (!capturingHotkey) return;
    e.preventDefault();
    if (e.code === "Escape") {
      stopCapturing(false);
      return;
    }
    const id = CODE_TO_ID[e.code];
    if (!id) return; // tecla sem equivalente reconhecido — ignorada
    heldDuringCapture.add(id);
    input.value = labelForCombo(Array.from(heldDuringCapture)) || "Pressione as teclas…";
  });

  window.addEventListener("keyup", function (e) {
    if (!capturingHotkey) return;
    e.preventDefault();
    const id = CODE_TO_ID[e.code];
    if (!id) return;
    // Solta a primeira tecla da combinação -> finaliza a captura com o
    // que estava pressionado no auge (todas as outras já foram
    // acumuladas nos keydowns anteriores, antes desta primeira soltura).
    if (heldDuringCapture.size > 0) stopCapturing(true);
  });
}

setupHotkeyCapture();

// ------------------------------------------------------------------ painéis

function onOllamaStatus(online) {
  const dot = document.getElementById("ollama-dot");
  const txt = document.getElementById("ollama-text");
  dot.className = "w-2 h-2 rounded-full " + (online ? "bg-primary" : "bg-error");
  txt.textContent = online ? "Ollama: online" : "Ollama: offline";
}

function onInfo(info) {
  document.getElementById("gpu-text").textContent = info.gpu || "";
  document.getElementById("rec-hotkey").textContent = info.hotkey_label ? "Atalho: " + info.hotkey_label : "";
  fillSelect("sel-whisper", info.whisper_options, info.whisper);
  fillSelect("sel-ollama", info.ollama_options, info.ollama);
  hotkeyIds = info.hotkey || [];
  document.getElementById("hotkey-input").value = labelForCombo(hotkeyIds);
  dirty = false;
  setStatus("");
}

function fillSelect(id, options, selected) {
  if (!options) return;
  const el = document.getElementById(id);
  el.innerHTML = "";
  options.forEach(function (opt) {
    // opt = [valor, rótulo] ou string simples
    const value = Array.isArray(opt) ? opt[0] : opt;
    const label = Array.isArray(opt) ? opt[1] : opt;
    const o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    if (value === selected) o.selected = true;
    el.appendChild(o);
  });
}

function onHistory(entry) {
  const body = document.getElementById("history-body");
  const empty = document.getElementById("history-empty");
  if (empty) empty.remove();

  const tr = document.createElement("tr");
  tr.className = "hover:bg-surface-container-highest transition-colors rounded-xl";
  tr.innerHTML =
    '<td class="px-4 py-3 text-on-surface-variant tabular-nums">' + esc(entry.time) + "</td>" +
    '<td class="px-4 py-3 font-bold text-primary">' + esc(entry.text) + "</td>" +
    '<td class="px-4 py-3 text-on-surface-variant tabular-nums">' + esc(entry.transcribe) + "</td>" +
    '<td class="px-4 py-3 text-on-surface-variant tabular-nums">' + esc(entry.optimize) + "</td>";
  body.insertBefore(tr, body.firstChild);

  while (body.children.length > 50) body.removeChild(body.lastChild);
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function setStatus(msg) {
  document.getElementById("settings-status").textContent = msg || "";
}

// ------------------------------------------------------------------- inputs

["sel-whisper", "sel-ollama"].forEach(function (id) {
  document.getElementById(id).addEventListener("change", function () {
    dirty = true;
    setStatus("Alterações não salvas.");
  });
});
// O atalho tem seu próprio caminho pra marcar `dirty` — ver
// setupHotkeyCapture, já que não é um <select>/<input> comum disparando
// "change" normal (o valor é setado via JS, não digitado pelo usuário).

document.getElementById("btn-save").addEventListener("click", function () {
  if (!bridge) return;
  bridge.save_settings(
    document.getElementById("sel-whisper").value,
    document.getElementById("sel-ollama").value,
    hotkeyIds
  );
});

document.getElementById("btn-cancel").addEventListener("click", function () {
  if (bridge) bridge.request_info();
});

// Clique inicia/para a gravação. O ícone não muda aqui: quem decide o
// estado de verdade é o Python (via onState, disparado pelo mesmo sinal que
// a tecla de atalho usa) — assim um clique fora de hora (app ainda
// carregando, ou um ditado anterior em transcrição) não deixa o botão preso
// mostrando "gravando" sem gravação nenhuma acontecendo.
document.getElementById("mic-well").addEventListener("click", function () {
  if (!bridge) return;
  if (currentState === "LISTENING") {
    bridge.stop_recording();
  } else {
    bridge.start_recording();
  }
});

document.getElementById("btn-exit").addEventListener("click", function () {
  if (bridge) bridge.request_exit();
});

// -------------------------------------------------------------- QWebChannel

new QWebChannel(qt.webChannelTransport, function (channel) {
  bridge = channel.objects.bridge;

  bridge.stateChanged.connect(onState);
  bridge.audioLevel.connect(onAudioLevel);
  bridge.rawText.connect(function (t) { showText(t, true); });
  bridge.optimizedText.connect(function (t) { showText(t, false); });
  bridge.errorText.connect(function (t) { showText(t, false); });
  bridge.historyAdded.connect(onHistory);
  bridge.ollamaStatus.connect(onOllamaStatus);
  bridge.infoChanged.connect(onInfo);
  bridge.statusMessage.connect(setStatus);

  // Só agora o Python manda o snapshot inicial — antes disso o DOM não
  // estaria pronto para receber.
  bridge.request_info();
});

showView("record");
