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

// --------------------------------------------------- catálogo de modelos

// pending* = o que os botões da tela mostram e o que "Salvar" manda pro
// Python; saved* = o que veio do último snapshot (onInfo), ou seja, o que
// está DE FATO em uso agora — só usado pra decidir badge "Em uso" e travar
// o botão Excluir do modelo realmente ativo (ver buildModelCard).
let modelCatalog = { whisper: [], ollama: [] };
let pendingWhisperModel = null;
let pendingOllamaModel = null;
let savedWhisperModel = null;
let savedOllamaModel = null;
let modelModalKind = null;   // "whisper" | "ollama" | null (modal fechado)
// Chaves "kind:id" com job em andamento AGORA — vários ao mesmo tempo são
// permitidos (baixar dois modelos em paralelo, trocar pra um já baixado
// enquanto outro ainda baixa); só trava uma 2ª operação no MESMO modelo
// (ver Bridge.download_model/delete_model, que recusa isso do lado
// Python também).
let busyKeys = {};
let downloadPct = {};        // { "whisper:medium": 42.0 } — cache pra redesenhar
let deleteArmed = {};        // { "whisper:medium": timeoutId } — confirmação de 2 cliques
let availableVramGb = null;  // VRAM real da melhor GPU CUDA (0 = só CPU), null = ainda não chegou

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
// `wave` só é true em LISTENING: é o único estado em que áudio de verdade
// ainda está chegando do microfone. Em TRANSCRIBING/OPTIMIZING a gravação
// já parou — deixar `wave: true` ali faria as barras congelarem na última
// amostra real em vez de responder a nada, o que parece bug, não estado.
const STATE_UI = {
  LOADING:      { title: "Carregando modelos…", sub: "Aguarde — Whisper e Ollama estão subindo", live: false, wave: false },
  IDLE:         { title: "Pronto",              sub: "Clique no microfone ou segure a tecla de atalho", live: false, wave: false },
  LISTENING:    { title: "Ouvindo…",            sub: "Transcrevendo em tempo real",             live: true,  wave: true },
  TRANSCRIBING: { title: "Transcrevendo…",      sub: "Whisper está processando o áudio",        live: true,  wave: false },
  OPTIMIZING:   { title: "Processando…",        sub: "Ollama está revisando a transcrição",     live: true,  wave: false },
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
  if (!ui.wave) resetWaveBars();

  setMicButtonRecording(name === "LISTENING");

  if (name === "LISTENING") {
    document.getElementById("rec-content").hidden = true;
    document.getElementById("rec-empty").hidden = false;
    document.getElementById("rec-text").textContent = "";
    resetWaveBars(); // começa cada gravação sem histórico da anterior
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

// Espectro de áudio: TODAS as 11 barras respondem ao MESMO nível atual do
// microfone (onAudioLevel) — isso não é uma forma de onda viajando de um
// lado pro outro. Um peso fixo por barra (perfil "montanha", a do meio
// mais alta) mais um tremor leve fazem a mesma leitura de nível parecer
// várias barras de espectro em vez de um bloco uniforme subindo e
// descendo junto.
//
// A altura do <div> em si fica fixa (WAVE_MAX_PX, ver CSS) — quem
// representa o nível é transform: scaleY, não height. Animar height força
// reflow a cada uma das 11 barras a cada amostra; scaleY é só composição
// (GPU), sem tocar layout — mesmo efeito visual, sem o custo.
//
// Ballistics de VU-meter (2ª rodada, mais ágil a pedido do usuário — a 1ª
// pareceu pouco animada): sobe rápido (o pico da voz fica visível), desce
// devagar (rastro suave) — por isso a duração da transição CSS é setada
// por amostra, dependendo se a barra está crescendo ou encolhendo, em vez
// de uma duração fixa nos dois sentidos.
const WAVE_MIN_PX = 16;
const WAVE_MAX_PX = 48;
const WAVE_MIN_SCALE = WAVE_MIN_PX / WAVE_MAX_PX;
const WAVE_BAR_WEIGHTS = [0.45, 0.6, 0.75, 0.88, 0.97, 1.0, 0.97, 0.88, 0.75, 0.6, 0.45];
const WAVE_JITTER = 0.3; // +-30% -- cada barra oscila um pouco por conta própria
const WAVE_RISE_MS = 55;
const WAVE_FALL_MS = 170;
let waveLastScale = WAVE_BAR_WEIGHTS.map(function () { return WAVE_MIN_SCALE; });

function onAudioLevel(level) {
  const clamped = Math.min(1, Math.max(0, level));
  paintWaveBars(clamped);
}

function paintWaveBars(level) {
  const bars = document.querySelectorAll("#wave .wave-bar");
  bars.forEach(function (bar, i) {
    const weight = WAVE_BAR_WEIGHTS[i] !== undefined ? WAVE_BAR_WEIGHTS[i] : 1;
    const jitter = (1 - WAVE_JITTER) + Math.random() * (2 * WAVE_JITTER);
    const value = Math.min(1, level * weight * jitter);
    const scale = WAVE_MIN_SCALE + value * (1 - WAVE_MIN_SCALE);
    const rising = scale > (waveLastScale[i] || WAVE_MIN_SCALE);
    bar.style.transitionDuration = (rising ? WAVE_RISE_MS : WAVE_FALL_MS) + "ms";
    bar.style.transform = "scaleY(" + scale + ")";
    waveLastScale[i] = scale;
  });
}

// Chamado ao sair do estado ao vivo — devolve o controle da escala (e da
// duração da transição) pro CSS (.wave-idle), senão a última amostra real
// ficaria "presa" como estilo inline por cima da regra idle.
function resetWaveBars() {
  waveLastScale = WAVE_BAR_WEIGHTS.map(function () { return WAVE_MIN_SCALE; });
  document.querySelectorAll("#wave .wave-bar").forEach(function (bar) {
    bar.style.removeProperty("transform");
    bar.style.removeProperty("transition-duration");
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

// Fábrica em vez de uma instância fixa só pro atalho de ditado — o de
// ciclar perfis (ver cycleHotkeyCapture abaixo) usa o mesmo mecanismo de
// captura, só um campo/estado diferente. Cada instância tem seu PRÓPRIO
// `capturing`/`heldDuringCapture` via closure (nunca os dois campos
// "escutando" ao mesmo tempo na prática — clicar num sai do outro via
// blur), e devolve getIds/setIds pra quem chamou (btn-save/onInfo) ler e
// popular sem precisar saber do estado interno de captura.
function makeHotkeyCapture(inputId) {
  const input = document.getElementById(inputId);
  let ids = [];
  let capturing = false;
  let heldDuringCapture = new Set();

  function stopCapturing(commit) {
    capturing = false;
    input.classList.remove("ring-2", "ring-primary-container");
    if (commit && heldDuringCapture.size > 0) {
      ids = Array.from(heldDuringCapture);
      dirty = true;
      setStatus("Alterações não salvas.");
    }
    input.value = labelForCombo(ids);
    heldDuringCapture = new Set();
  }

  input.addEventListener("click", function () {
    if (capturing) return;
    capturing = true;
    heldDuringCapture = new Set();
    input.classList.add("ring-2", "ring-primary-container");
    input.value = "Pressione as teclas…";
  });

  input.addEventListener("blur", function () {
    if (capturing) stopCapturing(false);
  });

  window.addEventListener("keydown", function (e) {
    if (!capturing) return;
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
    if (!capturing) return;
    e.preventDefault();
    const id = CODE_TO_ID[e.code];
    if (!id) return;
    // Solta a primeira tecla da combinação -> finaliza a captura com o
    // que estava pressionado no auge (todas as outras já foram
    // acumuladas nos keydowns anteriores, antes desta primeira soltura).
    if (heldDuringCapture.size > 0) stopCapturing(true);
  });

  return {
    getIds: function () { return ids; },
    setIds: function (newIds) {
      ids = newIds || [];
      input.value = labelForCombo(ids);
    },
  };
}

const dictationHotkeyCapture = makeHotkeyCapture("hotkey-input");
const cycleHotkeyCapture = makeHotkeyCapture("cycle-hotkey-input");

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
  savedWhisperModel = pendingWhisperModel = info.whisper;
  savedOllamaModel = pendingOllamaModel = info.ollama;
  updateModelButtons();
  fillSelect("sel-device", info.device_options, info.device);
  dictationHotkeyCapture.setIds(info.hotkey || []);
  cycleHotkeyCapture.setIds(info.cycle_profile_hotkey || []);

  // Só mostra o seletor de dispositivo quando há de fato uma escolha —
  // uma GPU + CPU já são duas opções; só CPU (sem GPU CUDA) é uma só.
  const showDevice = (info.device_options || []).length > 1;
  document.getElementById("device-row").hidden = !showDevice;
  document.getElementById("device-divider").hidden = !showDevice;

  fillSelect("sel-input-device", info.input_device_options, info.input_device);
  fillSelect("sel-output-language", info.output_language_options, info.output_language);

  onProfiles(info.profiles, info.profile_id);
  onDictionary(info.dictionary || []);

  dirty = false;
  setStatus("");
}

// -------------------------------------------------------------- perfis (CRUD)

// Lista completa (id/name/prompt) vinda do Python — mesma fonte alimenta o
// select do Ditado (qual perfil usar no PRÓXIMO ditado, aplica na hora) e a
// aba Perfis (lista + formulário de edição). `editingProfileId` é o que está
// carregado no FORMULÁRIO agora, que não precisa ser o mesmo que está ATIVO
// pro ditado — dá pra editar um perfil sem trocar qual está em uso.
let currentProfiles = [];
let activeProfileId = null;
let editingProfileId = null;

function onProfiles(profiles, activeId) {
  currentProfiles = profiles || [];
  activeProfileId = activeId;
  fillSelect("sel-active-profile", currentProfiles.map(function (p) { return [p.id, p.name]; }), activeId);

  // Se o perfil que estava sendo editado sumiu (excluído em outra aba/
  // sessão), ou nada foi escolhido ainda, cai pro ativo.
  if (!currentProfiles.some(function (p) { return p.id === editingProfileId; })) {
    editingProfileId = activeId;
  }
  renderProfileList();
  loadProfileFormFromEditing();
}

function renderProfileList() {
  const list = document.getElementById("profile-list");
  list.innerHTML = "";
  currentProfiles.forEach(function (p) {
    const row = document.createElement("div");
    const isEditing = p.id === editingProfileId;
    row.className = "flex items-center justify-between gap-2 px-4 py-3 rounded-xl cursor-pointer transition-colors " +
      (isEditing
        ? "neu-inset bg-surface-container-low text-primary font-bold"
        : "hover:bg-surface-container-highest text-on-surface-variant");
    const label = document.createElement("span");
    label.className = "font-label-md text-label-md truncate";
    label.textContent = p.name;
    row.appendChild(label);
    // "Em uso" e "Fixo" nunca colidem no mesmo perfil na prática (o fixo
    // raramente é o ativo), mas ambos cabem juntos se acontecer.
    if (p.builtin) {
      const lock = document.createElement("span");
      lock.className = "material-symbols-outlined text-on-surface-variant opacity-60 shrink-0";
      lock.style.fontSize = "16px";
      lock.textContent = "lock";
      row.appendChild(lock);
    }
    if (p.id === activeProfileId) {
      const badge = document.createElement("span");
      badge.className = "font-label-sm text-label-sm text-primary opacity-80 shrink-0";
      badge.textContent = "Em uso";
      row.appendChild(badge);
    }
    row.addEventListener("click", function () {
      editingProfileId = p.id;
      renderProfileList();
      loadProfileFormFromEditing();
    });
    list.appendChild(row);
  });
}

function loadProfileFormFromEditing() {
  const profile = currentProfiles.find(function (p) { return p.id === editingProfileId; });
  const isBuiltin = !!(profile && profile.builtin);
  const nameEl = document.getElementById("profile-name");
  const promptEl = document.getElementById("profile-prompt");

  nameEl.value = profile ? profile.name : "";
  promptEl.value = isBuiltin
    ? "Sem prompt — a transcrição do Whisper é usada exatamente como sai, sem passar pelo Ollama."
    : (profile ? profile.prompt : "");

  nameEl.disabled = isBuiltin;
  promptEl.disabled = isBuiltin;
  document.getElementById("btn-profile-delete").hidden = !profile || isBuiltin;
  document.getElementById("btn-profile-save").hidden = isBuiltin;

  resetDeleteConfirm();
  setProfilesStatus(isBuiltin ? "Perfil fixo do sistema — não pode ser editado nem excluído." : "");
}

function setProfilesStatus(msg) {
  document.getElementById("profiles-status").textContent = msg || "";
}

// Sem confirm() nativo (bloquearia o QWebEngineView) — o próprio botão vira
// a confirmação: primeiro clique arma, segundo clique (dentro de 3s) exclui.
let deleteConfirmArmed = false;
let deleteConfirmTimer = null;

function resetDeleteConfirm() {
  deleteConfirmArmed = false;
  if (deleteConfirmTimer) { clearTimeout(deleteConfirmTimer); deleteConfirmTimer = null; }
  document.getElementById("btn-profile-delete").textContent = "Excluir";
}

document.getElementById("btn-profile-new").addEventListener("click", function () {
  editingProfileId = null;
  renderProfileList();
  document.getElementById("profile-name").value = "";
  document.getElementById("profile-prompt").value = "";
  document.getElementById("btn-profile-delete").hidden = true;
  resetDeleteConfirm();
  setProfilesStatus("");
  document.getElementById("profile-name").focus();
});

document.getElementById("btn-profile-save").addEventListener("click", function () {
  if (!bridge) return;
  bridge.save_profile(
    editingProfileId || "",
    document.getElementById("profile-name").value,
    document.getElementById("profile-prompt").value
  );
});

document.getElementById("btn-profile-delete").addEventListener("click", function () {
  if (!bridge || !editingProfileId) return;
  if (!deleteConfirmArmed) {
    deleteConfirmArmed = true;
    document.getElementById("btn-profile-delete").textContent = "Confirmar exclusão?";
    deleteConfirmTimer = setTimeout(resetDeleteConfirm, 3000);
    return;
  }
  const idToDelete = editingProfileId;
  resetDeleteConfirm();
  bridge.delete_profile(idToDelete);
});

document.getElementById("sel-active-profile").addEventListener("change", function () {
  if (bridge) bridge.select_profile(this.value);
});

// ----------------------------------------------------------- dicionário (CRUD)

let currentDictionary = [];

function onDictionary(words) {
  currentDictionary = words || [];
  renderDictionaryList();
}

function renderDictionaryList() {
  const box = document.getElementById("dictionary-list");
  box.innerHTML = "";
  if (!currentDictionary.length) {
    const empty = document.createElement("p");
    empty.className = "w-full text-on-surface-variant opacity-50 text-center py-6";
    empty.textContent = "Nenhuma palavra cadastrada ainda.";
    box.appendChild(empty);
    return;
  }
  // Chip compacto (largura pelo conteúdo, não pelo container) que quebra
  // linha sozinho — ver flex-wrap em #dictionary-list.
  currentDictionary.forEach(function (word) {
    const chip = document.createElement("div");
    chip.className = "inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1.5 rounded-full bg-background";
    const label = document.createElement("span");
    label.className = "font-body-md text-body-md text-on-surface";
    label.textContent = word;
    chip.appendChild(label);

    const del = document.createElement("button");
    del.type = "button";
    del.title = "Excluir";
    del.className = "flex items-center justify-center w-6 h-6 rounded-full text-on-surface-variant hover:text-error hover:bg-error/10 transition-colors shrink-0";
    const delIcon = document.createElement("span");
    delIcon.className = "material-symbols-outlined";
    delIcon.style.fontSize = "16px";
    delIcon.textContent = "delete";
    del.appendChild(delIcon);
    del.addEventListener("click", function () {
      if (!bridge) return;
      const key = "dict:" + word;
      if (!armDeleteButton(del, key, renderDictionaryList, function (btn) {
        // Confirmação de 2 cliques sem texto (o botão é só o ícone) — troca
        // pro ícone "definitivo" e acende vermelho até expirar/confirmar.
        btn.querySelector(".material-symbols-outlined").textContent = "delete_forever";
        btn.classList.add("text-error", "bg-error/10");
        btn.title = "Clique de novo para confirmar";
      })) return;
      bridge.delete_dictionary_word(word);
    });
    chip.appendChild(del);
    box.appendChild(chip);
  });
}

function addDictionaryWord() {
  if (!bridge) return;
  const input = document.getElementById("dictionary-input");
  const word = input.value.trim();
  if (!word) return;
  bridge.add_dictionary_word(word);
  input.value = "";
  input.focus();
}

function setDictionaryStatus(msg) {
  document.getElementById("dictionary-status").textContent = msg || "";
}

document.getElementById("btn-dictionary-add").addEventListener("click", addDictionaryWord);
document.getElementById("dictionary-input").addEventListener("keydown", function (e) {
  if (e.key === "Enter") addDictionaryWord();
});

let resetDictionaryArmed = false;
let resetDictionaryTimer = null;
document.getElementById("btn-reset-dictionary").addEventListener("click", function () {
  if (!bridge) return;
  const btn = document.getElementById("btn-reset-dictionary");
  if (!resetDictionaryArmed) {
    resetDictionaryArmed = true;
    btn.textContent = "Confirmar reinício?";
    resetDictionaryTimer = setTimeout(function () {
      resetDictionaryArmed = false;
      btn.textContent = "Reiniciar dicionário";
    }, 3000);
    return;
  }
  clearTimeout(resetDictionaryTimer);
  resetDictionaryArmed = false;
  btn.textContent = "Reiniciar dicionário";
  bridge.reset_dictionary();
});

// -------------------------------------------- sugestão de palavras (diff)

function normalizeWord(raw) {
  // minúsculas + remove pontuação só nas BORDAS (mantém hífen/apóstrofo
  // internos: "guarda-chuva", "d'água" continuam intactos).
  return raw.toLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
}

// Filtro de ruído — não é gramática, só evita sugerir função gramatical
// comum quando a correção adiciona uma frase inteira nova.
const DIFF_STOPWORDS = new Set([
  "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
  "em", "no", "na", "nos", "nas", "por", "pra", "para", "com", "sem", "que", "e",
  "ou", "mas", "se", "é", "foi", "era", "ser", "estar", "está", "eu", "tu", "ele",
  "ela", "nós", "eles", "elas", "me", "te", "lhe", "meu", "minha", "seu", "sua",
  "isso", "isto", "aquilo", "não", "sim", "já", "ainda", "muito", "mais", "menos",
  "também", "só", "aí", "então", "tá", "né",
]);

/**
 * Palavras candidatas a entrar no Dicionário: aparecem no texto NOVO,
 * normalizadas não existem em NENHUM lugar do texto ANTIGO, não são
 * stopword, e ainda não estão no Dicionário. Não é um diff alinhado
 * (LCS) de propósito — o objetivo não é mostrar QUAL trecho mudou, é
 * achar vocabulário que o Whisper nunca tentou; um alinhamento ainda
 * precisaria do mesmo filtro final pra evitar ruído de reordenação, sem
 * mudar o resultado prático. `display` preserva a forma/capitalização
 * como digitada (é o que vai pro Dicionário se o usuário confirmar).
 */
function suggestNewWords(oldText, newText, existingDictionaryWords) {
  const oldSet = new Set(oldText.split(/\s+/).map(normalizeWord).filter(Boolean));
  const known = new Set((existingDictionaryWords || []).map(normalizeWord));

  const suggestions = [];
  const seen = new Set();
  newText.split(/\s+/).forEach(function (tokenRaw) {
    const norm = normalizeWord(tokenRaw);
    if (!norm || norm.length < 2) return;
    if (oldSet.has(norm)) return;
    if (DIFF_STOPWORDS.has(norm)) return;
    if (known.has(norm)) return;
    if (seen.has(norm)) return;
    seen.add(norm);
    suggestions.push({ normalized: norm, display: tokenRaw.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "") });
  });
  return suggestions;
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

// ----------------------------------------------- modal de escolha de modelo

function labelFor(kind, id) {
  const found = (modelCatalog[kind] || []).find(function (m) { return m.id === id; });
  return found ? found.label : (id || "Selecionar…");
}

function updateModelButtons() {
  document.getElementById("btn-whisper-model").textContent = labelFor("whisper", pendingWhisperModel);
  document.getElementById("btn-ollama-model").textContent = labelFor("ollama", pendingOllamaModel);
}

function onModelCatalog(catalog) {
  modelCatalog = catalog || { whisper: [], ollama: [] };
  availableVramGb = typeof catalog.available_vram_gb === "number" ? catalog.available_vram_gb : null;
  updateModelButtons();
  updateVramIndicator();
  // Um download/exclusão pode terminar com o modal fechado (ver
  // onModelJobFinished) — só vale a pena redesenhar a lista se ela estiver
  // visível.
  if (modelModalKind) renderModelList();
}

function updateVramIndicator() {
  const el = document.getElementById("model-modal-vram");
  if (!el) return;
  if (availableVramGb === null) {
    el.textContent = "";
  } else if (availableVramGb > 0) {
    el.textContent = "Sua GPU tem ~" + Math.round(availableVramGb) + " GB de VRAM";
  } else {
    el.textContent = "Nenhuma GPU dedicada detectada — rodando na CPU";
  }
}

function openModelModal(kind) {
  modelModalKind = kind;
  document.getElementById("model-modal-title").textContent =
    kind === "whisper" ? "Modelo Whisper" : "Modelo Ollama";
  document.getElementById("model-modal").hidden = false;
  renderModelList();
}

function closeModelModal() {
  modelModalKind = null;
  document.getElementById("model-modal").hidden = true;
}

function renderModelList() {
  const kind = modelModalKind;
  const list = document.getElementById("model-modal-list");
  list.innerHTML = "";
  (modelCatalog[kind] || []).forEach(function (m) {
    list.appendChild(buildModelCard(kind, m));
  });
}

// O Ollama manda progresso em rajada (dezenas/centenas de chunks por
// segundo — ver ModelJobThread._run_ollama_download). Chamar
// renderModelList() (desmonta e remonta TODOS os cards, com box-shadow
// neumórfico em cada um — caro de repintar) direto a cada chunk satura a
// única thread de JS da página: o resto da UI (clique em botões,
// setStatus de outras abas) fica engasgado atrás desse volume, e mesmo a
// própria barra de progresso parece travada porque os repaints não
// acompanham. Agenda no máximo 1 redesenho por frame (~60/s) em vez de um
// por chunk — ainda reflete o estado mais recente, só não briga pela
// thread a cada mensagem.
let modelListRenderScheduled = false;
function scheduleModelListRender() {
  if (modelListRenderScheduled) return;
  modelListRenderScheduled = true;
  requestAnimationFrame(function () {
    modelListRenderScheduled = false;
    if (modelModalKind) renderModelList();
  });
}

function buildModelCard(kind, m) {
  const key = kind + ":" + m.id;
  const pending = kind === "whisper" ? pendingWhisperModel : pendingOllamaModel;
  const saved = kind === "whisper" ? savedWhisperModel : savedOllamaModel;
  // Só o card DESTE modelo reflete um job em andamento — os outros cards
  // continuam clicáveis (baixar outro modelo em paralelo, trocar pra um já
  // instalado enquanto este baixa etc.).
  const isThisJob = !!busyKeys[key];

  const card = document.createElement("div");
  card.className = "neu-inset rounded-xl p-4 flex flex-col gap-2";

  const top = document.createElement("div");
  top.className = "flex items-center justify-between gap-2";
  const title = document.createElement("span");
  title.className = "font-label-md text-label-md text-on-background font-bold";
  title.textContent = m.label;
  top.appendChild(title);

  const badges = document.createElement("div");
  badges.className = "flex items-center gap-2";
  // Estimativa de VRAM contra a VRAM real da GPU do usuário — só avisa,
  // nunca desabilita nenhuma ação (ver legenda no header do modal e
  // gpu_devices.best_vram_gb): o Whisper na CPU ignora VRAM, e o Ollama
  // costuma descarregar parte do modelo pra CPU em vez de falhar.
  const insufficientVram =
    typeof m.vram_gb === "number" && availableVramGb !== null && m.vram_gb > availableVramGb;
  if (insufficientVram) badges.appendChild(makeVramWarningBadge());
  if (m.id === saved) badges.appendChild(makeBadge("Em uso"));
  else if (m.id === pending) badges.appendChild(makeBadge("Selecionado"));
  top.appendChild(badges);
  card.appendChild(top);

  const info = document.createElement("p");
  info.className = "font-body-md text-body-md text-on-surface-variant";
  const parts = [];
  if (m.params) parts.push(m.params + " de parâmetros");
  if (m.disk) parts.push(m.disk + " em disco");
  if (m.vram) parts.push(m.vram + " de VRAM");
  let bits = parts.join(" · ");
  // Whisper: tamanhos oficiais, precisos mesmo antes de baixar. Ollama: só é
  // exato pro que já está instalado (dado real de `ollama.list()`, ver
  // Bridge._build_catalog) — o resto do catálogo é estimativa, e o usuário
  // precisa saber disso pra não interpretar "9 GB" como garantido.
  if (kind === "ollama" && !m.installed && bits) bits += " (estimativa)";
  info.textContent = bits + (m.note ? (bits ? " — " : "") + m.note : "");
  card.appendChild(info);

  const actions = document.createElement("div");
  actions.className = "flex items-center gap-3 mt-1";

  if (isThisJob) {
    // Barra de verdade (com % se movendo) só quando há progresso REAL pra
    // mostrar — hoje só o download do Ollama tem isso (ver
    // ModelJobThread._run_ollama_download). Exclusão (nos dois motores) e
    // download do Whisper (sem progresso granular disponível — ver
    // whisper_models.download) não têm número nenhum pra exibir; fingir
    // uma barra ali é enganoso (ou pior, ficava mostrando o texto padrão
    // "Baixando…" numa exclusão — bug real que isso corrige). Só spinner
    // + texto nesses casos.
    const pct = downloadPct[key];
    if (busyKeys[key] === "download" && kind === "ollama" && typeof pct === "number" && pct >= 0) {
      actions.appendChild(buildProgressBar(pct));
    } else if (busyKeys[key] === "delete") {
      actions.appendChild(buildSpinner("Excluindo…"));
    } else {
      actions.appendChild(buildSpinner("Baixando…"));
    }
  } else if (!m.installed) {
    const btn = document.createElement("button");
    btn.className = "px-6 py-2 rounded-lg font-label-md text-label-md text-on-primary bg-primary neu-raised border border-primary-container hover:bg-primary/90 transition-all duration-200";
    btn.textContent = "Baixar";
    btn.addEventListener("click", function () {
      if (!bridge) return;
      busyKeys[key] = "download";
      downloadPct[key] = -1;
      renderModelList();
      bridge.download_model(kind, m.id);
    });
    actions.appendChild(btn);
  } else {
    if (m.id !== pending) {
      const use = document.createElement("button");
      use.className = "px-6 py-2 rounded-lg font-label-md text-label-md text-on-primary bg-primary neu-raised border border-primary-container hover:bg-primary/90 transition-all duration-200";
      use.textContent = "Usar este modelo";
      use.addEventListener("click", function () {
        if (kind === "whisper") pendingWhisperModel = m.id; else pendingOllamaModel = m.id;
        dirty = true;
        setStatus("Alterações não salvas.");
        updateModelButtons();
        closeModelModal();
      });
      actions.appendChild(use);
    }
    if (m.id !== saved && m.id !== pending) {
      const del = document.createElement("button");
      del.className = "px-6 py-2 rounded-lg font-label-md text-label-md text-error hover:bg-error/10 transition-colors";
      del.textContent = deleteArmed[key] ? "Confirmar exclusão?" : "Excluir";
      del.addEventListener("click", function () {
        if (!bridge) return;
        if (!armDeleteButton(del, key, function () { if (modelModalKind) renderModelList(); })) return;
        busyKeys[key] = "delete";
        renderModelList();
        bridge.delete_model(kind, m.id);
      });
      actions.appendChild(del);
    }
  }
  card.appendChild(actions);
  return card;
}

function makeBadge(text) {
  const b = document.createElement("span");
  b.className = "font-label-sm text-label-sm text-primary opacity-80";
  b.textContent = text;
  return b;
}

// Mesmo ícone ("block") e cor (text-error) da legenda no header do modal —
// ver dashboard.html — pra ficar óbvio que os dois são a mesma coisa.
function makeVramWarningBadge() {
  const b = document.createElement("span");
  b.className = "flex items-center gap-1 font-label-sm text-label-sm text-error shrink-0";
  const icon = document.createElement("span");
  icon.className = "material-symbols-outlined";
  icon.style.fontSize = "16px";
  icon.textContent = "block";
  b.appendChild(icon);
  const label = document.createElement("span");
  label.textContent = "VRAM insuficiente";
  b.appendChild(label);
  return b;
}

// Só chamada quando há um número de verdade pra mostrar (ver buildModelCard
// — hoje só o download do Ollama qualifica). Nada de modo indeterminado
// aqui: uma barra sem % real seria a mesma barra "mentirosa" que motivou
// trocar por spinner nos outros casos.
function buildProgressBar(pct) {
  const clamped = Math.min(100, Math.max(0, pct));
  const wrap = document.createElement("div");
  wrap.className = "flex-1 flex items-center gap-3";
  const track = document.createElement("div");
  track.className = "flex-1 h-2 rounded-full neu-inset overflow-hidden";
  const fill = document.createElement("div");
  fill.className = "h-full bg-primary transition-all duration-200";
  fill.style.width = clamped + "%";
  track.appendChild(fill);
  wrap.appendChild(track);
  const label = document.createElement("span");
  label.className = "font-label-sm text-label-sm text-on-surface-variant tabular-nums w-10 text-right";
  label.textContent = Math.round(clamped) + "%";
  wrap.appendChild(label);
  return wrap;
}

// Pra tudo que NÃO tem progresso mensurável — exclusão (nos dois motores)
// e download do Whisper (sem gancho de progresso granular disponível — ver
// whisper_models.download). Nada de barra fingindo se mexer: só um ícone
// girando (Material Symbols "progress_activity", feito pra isso) + texto
// dizendo o que está rolando.
function buildSpinner(text) {
  const wrap = document.createElement("div");
  wrap.className = "flex-1 flex items-center gap-2";
  const icon = document.createElement("span");
  icon.className = "material-symbols-outlined animate-spin text-primary";
  icon.style.fontSize = "18px";
  icon.textContent = "progress_activity";
  wrap.appendChild(icon);
  const label = document.createElement("span");
  label.className = "font-label-sm text-label-sm text-on-surface-variant";
  label.textContent = text;
  wrap.appendChild(label);
  return wrap;
}

// Mesmo padrão de dois cliques do botão de excluir perfil (deleteConfirmArmed
// acima), mas por card — deleteArmed guarda um timer por chave "kind:id" em
// vez de uma flag global, já que vários cards de exclusão convivem no mesmo
// modal. Como cada card é recriado do zero a cada renderModelList() (ver
// buildModelCard), o texto do botão é decidido consultando este mapa na hora
// de montar, não guardado em estado interno do DOM.
function armDeleteButton(btn, key, onExpire, onArm) {
  if (!deleteArmed[key]) {
    deleteArmed[key] = setTimeout(function () {
      delete deleteArmed[key];
      onExpire();
    }, 3000);
    // onArm é opcional pra botões que não são texto puro (ex.: o chip do
    // Dicionário, só ícone) — sem ele, cai no padrão de trocar o texto.
    if (onArm) onArm(btn); else btn.textContent = "Confirmar exclusão?";
    return false;
  }
  clearTimeout(deleteArmed[key]);
  delete deleteArmed[key];
  return true;
}

function onModelJobProgress(kind, id, pct, statusText) {
  downloadPct[kind + ":" + id] = pct;
  if (modelModalKind === kind) scheduleModelListRender();
}

function onModelJobFinished(kind, id, action, success, message) {
  delete busyKeys[kind + ":" + id];
  delete downloadPct[kind + ":" + id];
  setStatus(message || "");
  // Não dá pra confiar só no modelCatalog que o Python reemite em seguida
  // (ver Bridge._on_job_finished) pra tirar a barra de progresso/exclusão
  // do card: os caminhos de rejeição (job já em andamento, modelo em uso —
  // ver Bridge.download_model/delete_model) respondem só com este sinal,
  // sem reemitir catálogo nenhum. Sem redesenhar aqui, o card ficava preso
  // mostrando a barra pra sempre até o modal ser fechado e reaberto.
  if (modelModalKind) renderModelList();
}

function onHistory(entry) {
  const body = document.getElementById("history-body");
  const empty = document.getElementById("history-empty");
  if (empty) empty.remove();

  body.insertBefore(buildHistoryCard(entry), body.firstChild);

  while (body.children.length > 50) body.removeChild(body.lastChild);
}

// Trunca cada texto em 2 linhas no card (via -webkit-line-clamp direto no
// estilo, em vez da classe line-clamp-2 do Tailwind — o suporte a essa
// utility varia entre versões, isso funciona sempre) — o texto inteiro só
// aparece no modal (ver openHistoryModal), que é pra onde o clique de
// expandir leva.
function clampTwoLines(el) {
  el.style.display = "-webkit-box";
  el.style.webkitBoxOrient = "vertical";
  el.style.webkitLineClamp = "2";
  el.style.overflow = "hidden";
}

function buildHistoryCard(entry) {
  // Perfil "Transcrição bruta" pula o Ollama de propósito — original e
  // otimizado ficam idênticos (ver worker.finish_session). Mostrar os dois
  // blocos duplicados nesse caso só confundiria; um só já cobre tudo.
  const sameText = entry.raw === entry.text;

  const card = document.createElement("div");
  card.className = "neu-inset rounded-2xl p-5 flex flex-col gap-3";

  const header = document.createElement("div");
  header.className = "flex items-center justify-between gap-3";
  const time = document.createElement("span");
  time.className = "font-label-md text-label-md text-on-surface-variant tabular-nums";
  time.textContent = entry.time;
  header.appendChild(time);

  const headerRight = document.createElement("div");
  headerRight.className = "flex items-center gap-3";
  const durations = document.createElement("span");
  durations.className = "font-label-sm text-label-sm text-on-surface-variant tabular-nums";
  durations.textContent = "Transcrição " + entry.transcribe + " · Otimização " + entry.optimize;
  headerRight.appendChild(durations);
  const expandBtn = document.createElement("button");
  expandBtn.type = "button";
  expandBtn.className = "text-on-surface-variant hover:text-primary transition-colors";
  expandBtn.title = "Expandir";
  const expandIcon = document.createElement("span");
  expandIcon.className = "material-symbols-outlined";
  expandIcon.style.fontSize = "18px";
  expandIcon.textContent = "open_in_full";
  expandBtn.appendChild(expandIcon);
  expandBtn.addEventListener("click", function () { openHistoryModal(entry); });
  headerRight.appendChild(expandBtn);
  header.appendChild(headerRight);
  card.appendChild(header);

  if (!sameText) {
    card.appendChild(buildHistoryTextBlock("Original", entry.raw, false, "text-on-surface-variant italic opacity-80"));
  }
  card.appendChild(buildHistoryTextBlock(sameText ? "Texto" : "Otimizado", entry.text, true, "text-primary font-bold"));

  // Guardado na própria entry pra saveRawCorrection poder substituir este
  // card por um novo depois de uma correção — sem isso, o card ficaria com
  // o texto (e o botão de copiar) desatualizados pra sempre, já que o
  // texto exibido aqui é uma cópia da string, não uma referência viva a
  // entry.raw/entry.text.
  entry.cardEl = card;

  return card;
}

function buildHistoryTextBlock(label, text, isMain, textClass) {
  const wrap = document.createElement("div");
  wrap.className = "flex flex-col gap-1";

  const row = document.createElement("div");
  row.className = "flex items-center justify-between gap-2";
  const labelEl = document.createElement("span");
  labelEl.className = "font-label-sm text-label-sm text-on-surface-variant";
  labelEl.textContent = label;
  row.appendChild(labelEl);
  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "text-on-surface-variant hover:text-primary transition-colors";
  copyBtn.title = "Copiar";
  const copyIcon = document.createElement("span");
  copyIcon.className = "material-symbols-outlined";
  copyIcon.style.fontSize = "16px";
  copyIcon.textContent = "content_copy";
  copyBtn.appendChild(copyIcon);
  copyBtn.addEventListener("click", function () { copyText(text, copyIcon); });
  row.appendChild(copyBtn);
  wrap.appendChild(row);

  const p = document.createElement("p");
  p.className = "font-body-md text-body-md " + textClass;
  p.textContent = text;
  clampTwoLines(p);
  wrap.appendChild(p);

  return wrap;
}

let currentModalEntry = null;   // entry aberta agora no modal (ver openHistoryModal)
let historyEditing = false;     // textarea de correção do Original está aberta agora?

function openHistoryModal(entry) {
  currentModalEntry = entry;
  exitRawEditMode();   // defensivo — nunca deveria chegar aqui em modo edição

  const sameText = entry.raw === entry.text;
  document.getElementById("history-modal-time").textContent = entry.time;
  document.getElementById("history-modal-durations").textContent =
    "Transcrição " + entry.transcribe + " · Otimização " + entry.optimize;

  // O bloco "Original" (raw) é o EDITÁVEL — fica sempre visível, é o
  // texto que a pessoa realmente falou, mesmo no perfil "Transcrição
  // bruta" (onde raw === text, e só o bloco Otimizado, redundante, some).
  document.getElementById("history-modal-raw-wrap").hidden = false;
  document.querySelector("#history-modal-raw-wrap .font-label-md").textContent = sameText ? "Texto" : "Original";
  document.getElementById("history-modal-raw").textContent = entry.raw;

  document.getElementById("history-modal-optimized-wrap").hidden = sameText;
  document.getElementById("history-modal-text").textContent = entry.text;

  document.getElementById("history-modal-copy-raw").onclick = function () {
    copyText(currentModalEntry.raw, this.querySelector(".material-symbols-outlined"));
  };
  document.getElementById("history-modal-copy-text").onclick = function () {
    copyText(currentModalEntry.text, this.querySelector(".material-symbols-outlined"));
  };

  document.getElementById("history-modal-suggestions").hidden = true;
  document.getElementById("history-modal-raw-saved-msg").hidden = true;
  document.getElementById("history-modal").hidden = false;
}

function closeHistoryModal() {
  document.getElementById("history-modal").hidden = true;
  // Descarta uma edição não salva, se houver — sem confirm() nativo (que
  // travaria o QWebEngineView), fechar sem salvar é o próprio "cancelar".
  // Uma correção JÁ salva (saveRawCorrection já rodou) não se perde: já
  // está em entry.raw/entry.cardEl, client-side, e histórico não é
  // persistido em disco mesmo — não há nada a sincronizar com o Python
  // além dos cliques em "+" nas sugestões.
  exitRawEditMode();
  document.getElementById("history-modal-suggestions").hidden = true;
  currentModalEntry = null;
}

function enterRawEditMode() {
  historyEditing = true;
  document.getElementById("history-modal-raw").hidden = true;
  document.getElementById("history-modal-edit-raw").hidden = true;
  document.getElementById("history-modal-suggestions").hidden = true;
  document.getElementById("history-modal-raw-saved-msg").hidden = true;
  const ta = document.getElementById("history-modal-raw-textarea");
  ta.value = currentModalEntry.raw;
  document.getElementById("history-modal-raw-edit").hidden = false;
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
}

function exitRawEditMode() {
  historyEditing = false;
  document.getElementById("history-modal-raw-edit").hidden = true;
  document.getElementById("history-modal-raw").hidden = false;
  document.getElementById("history-modal-edit-raw").hidden = false;
}

function saveRawCorrection() {
  const entry = currentModalEntry;
  if (!entry) return;
  const newRaw = document.getElementById("history-modal-raw-textarea").value.trim();
  if (!newRaw) return;                                      // não aceita ficar vazio
  if (newRaw === entry.raw) { exitRawEditMode(); return; }   // nada mudou de verdade

  const wasSameText = entry.raw === entry.text;
  const suggestions = suggestNewWords(entry.raw, newRaw, currentDictionary);

  entry.raw = newRaw;
  if (wasSameText) entry.text = newRaw;   // os dois eram conceitualmente o mesmo campo

  exitRawEditMode();
  document.getElementById("history-modal-raw").textContent = newRaw;

  const nowSameText = entry.raw === entry.text;
  document.getElementById("history-modal-optimized-wrap").hidden = nowSameText;
  document.querySelector("#history-modal-raw-wrap .font-label-md").textContent = nowSameText ? "Texto" : "Original";

  // Reconstrói o card na lista (ver comentário em buildHistoryCard) — a
  // correção reflete na hora, não só dentro do modal. Precisa guardar o
  // card ANTIGO antes de chamar buildHistoryCard: ela já atualiza
  // entry.cardEl pro card NOVO como efeito colateral, então pedir
  // entry.cardEl DEPOIS dessa chamada seria o card se substituindo por
  // si mesmo — o antigo nunca sairia da tela.
  const oldCard = entry.cardEl;
  const newCard = buildHistoryCard(entry);
  oldCard.replaceWith(newCard);

  if (suggestions.length === 0) {
    const msg = document.getElementById("history-modal-raw-saved-msg");
    msg.hidden = false;
    setTimeout(function () { msg.hidden = true; }, 2500);
    return;
  }
  renderHistorySuggestions(suggestions);
}

function renderHistorySuggestions(suggestions) {
  const wrap = document.getElementById("history-modal-suggestions");
  const list = document.getElementById("history-modal-suggestions-list");
  list.innerHTML = "";
  suggestions.forEach(function (s) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "flex items-center gap-1 px-3 py-1.5 rounded-full neu-button font-label-sm text-label-sm text-primary transition-all";
    const icon = document.createElement("span");
    icon.className = "material-symbols-outlined";
    icon.style.fontSize = "14px";
    icon.textContent = "add";
    chip.appendChild(icon);
    chip.appendChild(document.createTextNode(s.display));
    chip.addEventListener("click", function () {
      if (!bridge || chip.disabled) return;
      chip.disabled = true;
      icon.textContent = "check";
      chip.classList.add("opacity-60");
      bridge.add_dictionary_word(s.display);
      setTimeout(function () {
        chip.remove();
        if (!list.children.length) wrap.hidden = true;
      }, 1200);
    });
    list.appendChild(chip);
  });
  wrap.hidden = false;
}

document.getElementById("history-modal-edit-raw").addEventListener("click", enterRawEditMode);
document.getElementById("history-modal-raw-cancel").addEventListener("click", exitRawEditMode);
document.getElementById("history-modal-raw-save").addEventListener("click", saveRawCorrection);
document.getElementById("history-modal-suggestions-dismiss").addEventListener("click", function () {
  document.getElementById("history-modal-suggestions").hidden = true;
});

// Cópia via Bridge (área de transferência nativa do Qt) em vez de
// navigator.clipboard.writeText — a página roda de um file:// dentro do
// QWebEngineView sem handler de permissão configurado, então a Clipboard
// API do navegador falharia/pendura sem aviso. Dá um feedback visual
// rápido (troca o ícone por um check) em vez de um texto "Copiado!" à
// parte, pra não precisar de mais um elemento de status.
function copyText(text, iconEl) {
  if (!bridge || !text) return;
  bridge.copy_to_clipboard(text);
  if (!iconEl) return;
  const original = iconEl.textContent;
  iconEl.textContent = "check";
  setTimeout(function () { iconEl.textContent = original; }, 1200);
}

function setStatus(msg) {
  document.getElementById("settings-status").textContent = msg || "";
}

// ------------------------------------------------------------------- inputs

["sel-device", "sel-input-device", "sel-output-language"].forEach(function (id) {
  document.getElementById(id).addEventListener("change", function () {
    dirty = true;
    setStatus("Alterações não salvas.");
  });
});
// O atalho tem seu próprio caminho pra marcar `dirty` — ver
// setupHotkeyCapture, já que não é um <select>/<input> comum disparando
// "change" normal (o valor é setado via JS, não digitado pelo usuário). Os
// modelos Whisper/Ollama idem — marcam dirty dentro do próprio handler de
// "Usar este modelo" no modal (ver buildModelCard).

document.getElementById("btn-whisper-model").addEventListener("click", function () { openModelModal("whisper"); });
document.getElementById("btn-ollama-model").addEventListener("click", function () { openModelModal("ollama"); });
document.getElementById("model-modal-close").addEventListener("click", closeModelModal);
document.getElementById("model-modal").addEventListener("click", function (e) {
  if (e.target === this) closeModelModal(); // clique no backdrop fecha
});

document.getElementById("history-modal-close").addEventListener("click", closeHistoryModal);
document.getElementById("history-modal").addEventListener("click", function (e) {
  if (e.target === this) closeHistoryModal();
});

document.getElementById("btn-save").addEventListener("click", function () {
  if (!bridge) return;
  bridge.save_settings(
    pendingWhisperModel,
    pendingOllamaModel,
    dictationHotkeyCapture.getIds(),
    cycleHotkeyCapture.getIds(),
    document.getElementById("sel-device").value,
    document.getElementById("sel-input-device").value,
    document.getElementById("sel-output-language").value
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
  bridge.profilesChanged.connect(onProfiles);
  bridge.profileStatusMessage.connect(setProfilesStatus);
  bridge.modelCatalog.connect(onModelCatalog);
  bridge.modelJobProgress.connect(onModelJobProgress);
  bridge.modelJobFinished.connect(onModelJobFinished);
  bridge.dictionaryChanged.connect(onDictionary);
  bridge.dictionaryStatusMessage.connect(setDictionaryStatus);

  // Só agora o Python manda o snapshot inicial — antes disso o DOM não
  // estaria pronto para receber.
  bridge.request_info();
  bridge.request_model_catalog();
});

showView("record");
