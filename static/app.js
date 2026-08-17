const state = {
  path: "/",
  items: [],
  selected: null,
  history: [],
  terminalOpen: false,
  historyOpen: false,
  previewOpen: false,
  connUser: "root",
  connHost: "vps",
  termCwd: "~",
};

// ── API ──

async function api(endpoint, body = {}) {
  const res = await fetch(`/api/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (data.command) {
    showCommand(data.command);
    addHistory(data.command);
  }
  return data;
}

// ── Command Bar ──

function showCommand(cmd) {
  document.getElementById("cmd-text").textContent = cmd;
}

function copyCommand() {
  const cmd = document.getElementById("cmd-text").textContent;
  navigator.clipboard.writeText(cmd);
  const btn = document.querySelector("#command-bar .copy-btn");
  btn.textContent = "copiado!";
  setTimeout(() => (btn.textContent = "copiar"), 1500);
}

// ── History ──

function addHistory(cmd) {
  const now = new Date();
  const time = now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  state.history.unshift({ cmd, time });
  if (state.history.length > 100) state.history.pop();
  renderHistory();
}

function renderHistory() {
  const list = document.getElementById("history-list");
  if (!list) return;
  list.innerHTML = state.history
    .map(
      (h) => `
    <div class="history-item" onclick="navigator.clipboard.writeText('${h.cmd.replace(/'/g, "\\'")}')">
      <div class="time">${h.time}</div>
      <div class="cmd">$ ${escHtml(h.cmd)}</div>
    </div>`
    )
    .join("");
}

function toggleHistory() {
  state.historyOpen = !state.historyOpen;
  document.getElementById("history-panel").classList.toggle("open", state.historyOpen);
}

// ── Breadcrumb ──

function renderBreadcrumb() {
  const el = document.getElementById("breadcrumb");
  const parts = state.path.split("/").filter(Boolean);
  let html = `<span onclick="navigate('/')">/</span>`;
  let accumulated = "";
  for (const p of parts) {
    accumulated += "/" + p;
    const path = accumulated;
    html += `<span class="sep">/</span><span onclick="navigate('${path}')">${escHtml(p)}</span>`;
  }
  el.innerHTML = html;
}

// ── Navigate ──

async function navigate(path) {
  state.path = path;
  state.selected = null;
  renderBreadcrumb();

  const list = document.getElementById("file-list");
  list.innerHTML = '<div class="loading">carregando...</div>';

  const data = await api("ls", { path });
  state.items = data.items || [];

  // Sort: dirs first, then alphabetical
  state.items.sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  renderFiles();
}

function renderFiles() {
  const list = document.getElementById("file-list");
  const fragment = document.createDocumentFragment();

  // Parent dir row
  if (state.path !== "/") {
    const parent = state.path.replace(/\/[^/]+\/?$/, "") || "/";
    const parentRow = document.createElement("div");
    parentRow.className = "file-row";
    parentRow.innerHTML = `
        <div class="icon">&#128281;</div>
        <div class="name dir">..</div>
        <div class="size"></div>
        <div class="owner"></div>
        <div class="date"></div>`;
    parentRow.addEventListener("dblclick", () => navigate(parent));
    fragment.appendChild(parentRow);
  }

  for (const item of state.items) {
    const fullPath = state.path === "/" ? `/${item.name}` : `${state.path}/${item.name}`;
    const icon = item.is_dir ? "&#128193;" : fileIcon(item.name);
    const nameClass = item.is_dir ? "name dir" : "name";
    const size = item.is_dir ? "-" : formatSize(item.size);

    const row = document.createElement("div");
    row.className = "file-row";
    row.dataset.path = fullPath;
    row.dataset.isdir = item.is_dir;
    row.dataset.name = item.name;
    row.innerHTML = `
        <div class="icon">${icon}</div>
        <div class="${nameClass}">${escHtml(item.name)}</div>
        <div class="size">${size}</div>
        <div class="owner">${escHtml(item.owner)}</div>
        <div class="date">${escHtml(item.date)}</div>`;
    row.addEventListener("click", () => selectItem(row));
    row.addEventListener("dblclick", () => openItem(fullPath, item.is_dir));
    row.addEventListener("contextmenu", (e) => showContextMenu(e, fullPath, item.is_dir, item.name));
    fragment.appendChild(row);
  }

  list.innerHTML = "";
  if (fragment.children.length === 0) {
    list.innerHTML = '<div class="loading">pasta vazia</div>';
  } else {
    list.appendChild(fragment);
  }
}

function selectItem(el) {
  document.querySelectorAll(".file-row.selected").forEach((r) => r.classList.remove("selected"));
  el.classList.add("selected");
  state.selected = {
    path: el.dataset.path,
    isDir: el.dataset.isdir === "true",
    name: el.dataset.name,
  };
}

async function openItem(path, isDir) {
  if (isDir) {
    navigate(path);
  } else {
    await viewFile(path);
  }
}

// ── File Viewer ──

async function viewFile(path) {
  const panel = document.getElementById("preview-panel");
  const content = document.getElementById("preview-content");
  const title = document.querySelector("#preview-header .title");

  panel.classList.add("open");
  state.previewOpen = true;
  title.textContent = path.split("/").pop();
  content.textContent = "carregando...";

  const data = await api("cat", { path, max_lines: 200 });
  content.textContent = data.content || data.error || "(vazio)";
}

function closePreview() {
  document.getElementById("preview-panel").classList.remove("open");
  state.previewOpen = false;
}

// ── Context Menu ──

function showContextMenu(e, path, isDir, name) {
  e.preventDefault();
  const menu = document.getElementById("context-menu");
  menu.innerHTML = "";

  function addBtn(icon, label, onClick, danger) {
    const btn = document.createElement("button");
    if (danger) btn.className = "danger";
    btn.innerHTML = `<span class="icon">${icon}</span> ${label}`;
    btn.addEventListener("click", () => { hideContextMenu(); onClick(); });
    menu.appendChild(btn);
  }

  function addSep() {
    menu.appendChild(document.createElement("hr"));
  }

  if (isDir) {
    addBtn("&#128193;", "Abrir pasta", () => navigate(path));
  } else {
    addBtn("&#128196;", "Visualizar", () => viewFile(path));
    addBtn("&#9998;", "Editar", () => editFile(path));
    addBtn("&#128203;", "Tail (ultimas linhas)", () => tailFile(path));
  }
  addSep();
  addBtn("&#9999;", "Renomear", () => renameItem(path, name));
  addBtn("&#8505;", "Detalhes (stat)", () => infoItem(path));
  addSep();
  addBtn("&#128465;", "Excluir", () => deleteItem(path, isDir, name), true);

  menu.style.left = e.clientX + "px";
  menu.style.top = e.clientY + "px";
  menu.style.display = "block";
}

function hideContextMenu() {
  document.getElementById("context-menu").style.display = "none";
}

document.addEventListener("click", hideContextMenu);

// ── Actions ──

async function createFolder() {
  const name = prompt("Nome da nova pasta:");
  if (!name) return;
  const path = state.path === "/" ? `/${name}` : `${state.path}/${name}`;
  await api("mkdir", { path });
  navigate(state.path);
}

async function createFile() {
  const name = prompt("Nome do novo arquivo:");
  if (!name) return;
  const path = state.path === "/" ? `/${name}` : `${state.path}/${name}`;
  await api("write", { path, content: "" });
  navigate(state.path);
}

async function deleteItem(path, isDir, name) {
  if (!confirm(`Excluir ${isDir ? "pasta" : "arquivo"} "${name}"?`)) return;
  await api("rm", { path, is_dir: isDir });
  closePreview();
  navigate(state.path);
}

async function renameItem(path, oldName) {
  const newName = prompt("Novo nome:", oldName);
  if (!newName || newName === oldName) return;
  const dir = path.substring(0, path.lastIndexOf("/"));
  const dst = dir + "/" + newName;
  await api("mv", { src: path, dst });
  navigate(state.path);
}

async function editFile(path) {
  const data = await api("cat", { path, max_lines: 5000 });
  const content = data.content || "";

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <h3>${escHtml(path.split("/").pop())}</h3>
      <textarea id="edit-content">${escHtml(content)}</textarea>
      <div class="actions">
        <button class="cancel" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="confirm" onclick="saveEdit('${escAttr(path)}')">Salvar</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
}

async function saveEdit(path) {
  const content = document.getElementById("edit-content").value;
  await api("write", { path, content });
  document.querySelector(".modal-overlay").remove();
  if (state.previewOpen) viewFile(path);
}

async function tailFile(path) {
  const panel = document.getElementById("preview-panel");
  const content = document.getElementById("preview-content");
  const title = document.querySelector("#preview-header .title");

  panel.classList.add("open");
  state.previewOpen = true;
  title.textContent = "tail: " + path.split("/").pop();
  content.textContent = "carregando...";

  const data = await api("tail", { path, lines: 50 });
  content.textContent = data.content || data.error || "(vazio)";
}

async function infoItem(path) {
  const panel = document.getElementById("preview-panel");
  const content = document.getElementById("preview-content");
  const title = document.querySelector("#preview-header .title");

  panel.classList.add("open");
  state.previewOpen = true;
  title.textContent = "stat: " + path.split("/").pop();
  content.textContent = "carregando...";

  const data = await api("info", { path });
  content.textContent = data.content || data.error || "";
}

// ── Sidebar shortcuts ──

async function goHome() { navigate("/root"); }
async function goRoot() { navigate("/"); }
async function goOpt() { navigate("/opt"); }
async function goEtc() { navigate("/etc"); }
async function goVarLog() { navigate("/var/log"); }

async function showDisk() {
  const data = await api("disk");
  showSpecialContent("Disco e Memoria", data.content);
}

async function showDocker() {
  const data = await api("docker/ps");
  showSpecialContent("Docker Containers", data.content || data.error);
}

async function showServices() {
  const data = await api("services");
  showSpecialContent("Servicos Ativos", data.content || data.error);
}

async function showDockerLogs(name) {
  if (!name) name = prompt("Nome do container:");
  if (!name) return;
  const data = await api("docker/logs", { name, lines: 80 });
  showSpecialContent(`Logs: ${name}`, data.content);
}

function showSpecialContent(title, content) {
  const panel = document.getElementById("preview-panel");
  const contentEl = document.getElementById("preview-content");
  const titleEl = document.querySelector("#preview-header .title");

  panel.classList.add("open");
  state.previewOpen = true;
  titleEl.textContent = title;
  contentEl.textContent = content;
}

// ── Terminal ──

function toggleTerminal() {
  state.terminalOpen = !state.terminalOpen;
  document.getElementById("terminal-panel").classList.toggle("open", state.terminalOpen);
  if (state.terminalOpen) {
    document.getElementById("terminal-input").focus();
  }
}

async function terminalExec() {
  const input = document.getElementById("terminal-input");
  const output = document.getElementById("terminal-output");
  const cmd = input.value.trim();
  if (!cmd) return;

  input.value = "";
  const promptUser = state.connUser || "root";
  const promptHost = state.connHost || "vps";
  const promptCwd = state.termCwd || "~";
  output.innerHTML += `<span style="color:var(--green)">${escHtml(promptUser)}@${escHtml(promptHost)}</span>:<span style="color:var(--accent)">${escHtml(promptCwd)}</span>$ ${escHtml(cmd)}\n`;

  const data = await api("exec", { command: cmd });
  if (data.stdout) output.innerHTML += escHtml(data.stdout);
  if (data.stderr) output.innerHTML += `<span style="color:var(--red)">${escHtml(data.stderr)}</span>`;
  if (data.exit_code !== 0) {
    output.innerHTML += `<span style="color:var(--red)">[exit ${data.exit_code}]</span>\n`;
  }

  // Update cwd from server response (cd persists!)
  if (data.cwd) {
    state.termCwd = data.cwd;
    const promptEl = document.getElementById("terminal-prompt");
    if (promptEl) promptEl.textContent = `${promptUser}@${promptHost}:${data.cwd}$`;
  }

  output.scrollTop = output.scrollHeight;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "F12" || (e.ctrlKey && e.key === "`")) {
    e.preventDefault();
    toggleTerminal();
  }
});

// ── Helpers ──

function escHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function escAttr(s) {
  return s.replace(/'/g, "\\'").replace(/"/g, "&quot;");
}

function formatSize(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + " " + units[i];
}

function fileIcon(name) {
  const ext = name.split(".").pop().toLowerCase();
  const icons = {
    py: "&#128013;", js: "&#9883;", ts: "&#9883;", json: "&#128196;",
    md: "&#128196;", txt: "&#128196;", log: "&#128203;", sh: "&#9881;",
    conf: "&#9881;", ini: "&#9881;", yml: "&#9881;", yaml: "&#9881;",
    service: "&#9881;",
  };
  return icons[ext] || "&#128196;";
}

// ── Connection ──

async function doConnect() {
  const host = document.getElementById("login-host").value.trim();
  const port = document.getElementById("login-port").value || "22";
  const user = document.getElementById("login-user").value.trim() || "root";
  const pass = document.getElementById("login-pass").value;
  const errEl = document.getElementById("login-error");
  const btn = document.getElementById("login-btn");

  if (!host) { errEl.textContent = "Digite o IP ou hostname"; return; }

  errEl.textContent = "";
  btn.textContent = "conectando...";
  btn.classList.add("loading");

  const data = await api("connect", { host, port: parseInt(port), user, password: pass });

  btn.textContent = "conectar";
  btn.classList.remove("loading");

  if (data.success) {
    state.connUser = data.user;
    state.connHost = data.host;
    state.termCwd = "~";
    document.getElementById("login-screen").style.display = "none";
    document.getElementById("app").style.display = "flex";
    document.getElementById("conn-info").textContent = `${data.user}@${data.host}`;
    document.getElementById("terminal-prompt").textContent = `${data.user}@${data.host}:~$`;
    navigate("/root");
  } else {
    errEl.textContent = data.error || "Falha na conexao";
  }
}

async function doDisconnect() {
  await api("disconnect");
  document.getElementById("app").style.display = "none";
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("login-error").textContent = "";
  state.history = [];
}

// ── Init ──
// Check if already connected (page refresh)
(async () => {
  const data = await api("status");
  if (data.connected) {
    state.connUser = data.user;
    state.connHost = data.host;
    state.termCwd = "~";
    document.getElementById("login-screen").style.display = "none";
    document.getElementById("app").style.display = "flex";
    document.getElementById("conn-info").textContent = `${data.user}@${data.host}`;
    document.getElementById("terminal-prompt").textContent = `${data.user}@${data.host}:~$`;
    navigate("/root");
  }
})();
