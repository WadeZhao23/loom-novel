"use strict";

const $ = (id) => document.getElementById(id);
let DATA = null;            // 当前项目 state
let CUR = null;             // 当前打开的文件 {rel, editable, chapter}
let _lastLearnChapter = null;  // 最近一次 learn 的章号(供撤销)

// ---------- 小工具 ----------
async function jreq(method, url, body) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(url, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `请求失败 (${r.status})`);
  return data;
}
function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast hidden"), 3200);
}

// ---------- 启动 ----------
window.addEventListener("DOMContentLoaded", () => {
  bind();
  loadGenres();
  const saved = localStorage.getItem("loom_root");
  if (saved) openProject(saved, true);
});

async function loadGenres() {
  try {
    const d = await jreq("GET", "/api/genres");
    const sel = $("new-genre");
    (d.genres || []).forEach((g) => {
      const o = document.createElement("option");
      o.value = g; o.textContent = g;
      sel.appendChild(o);
    });
  } catch (e) { /* 题材是可选增益,拉不到就只留"不选题材" */ }
}

function bind() {
  $("btn-create").onclick = createProject;
  $("btn-open").onclick = () => openProject($("open-path").value.trim(), false);
  $("btn-close-proj").onclick = () => { localStorage.removeItem("loom_root"); showWelcome(); };
  $("btn-doctor").onclick = runDoctor;
  $("btn-save-backend").onclick = saveBackend;
  $("provider").onchange = () => { if ($("provider").value === "deepseek") $("model").value = "deepseek-chat"; };
  $("btn-write-next").onclick = () => writeChapter(DATA.next_chapter, false);
  $("btn-seed").onclick = () => { $("seed-error").textContent = ""; $("seed-overlay").classList.remove("hidden"); };
  $("seed-cancel").onclick = () => $("seed-overlay").classList.add("hidden");
  $("seed-go").onclick = doSeed;
  $("btn-save-file").onclick = saveFile;
  $("btn-learn").onclick = () => CUR && learn(CUR.chapter);
  $("learn-keep").onclick = () => { $("learn-overlay").classList.add("hidden"); openFile("外置大脑/写作指纹.md", true, null); };
  $("learn-revert").onclick = revertLearn;
  $("run-close").onclick = closeRun;
}

// ---------- 项目 ----------
async function createProject() {
  $("welcome-error").textContent = "";
  try {
    const d = await jreq("POST", "/api/project/create",
      { name: $("new-name").value.trim(), parent: $("new-parent").value.trim(), genre: $("new-genre").value || null });
    enterProject(d);
  } catch (e) { $("welcome-error").textContent = e.message; }
}
async function openProject(root, silent) {
  try {
    const d = await jreq("POST", "/api/project/open", { root });
    enterProject(d);
  } catch (e) {
    if (silent) { showWelcome(); } else { $("welcome-error").textContent = e.message; }
  }
}
function showWelcome() {
  $("app").classList.add("hidden");
  $("welcome").classList.remove("hidden");
}
function enterProject(d) {
  DATA = d;
  localStorage.setItem("loom_root", d.root);
  $("welcome").classList.add("hidden");
  $("app").classList.remove("hidden");
  render();
}

async function refresh() {
  DATA = await jreq("GET", `/api/project/state?root=${encodeURIComponent(DATA.root)}`);
  render();
}

// ---------- 启动自检(只读) ----------
async function runDoctor() {
  try {
    const d = await jreq("GET", `/api/doctor?root=${encodeURIComponent(DATA.root)}`);
    const bad = d.checks.filter((c) => !c.ok);
    if (!bad.length) { toast("环境就绪,可以开写"); return; }
    bad.forEach((c) => toast(`✗ ${c.name}:${c.missing} → ${c.fix}`, true));
  } catch (e) { toast(e.message, true); }
}

// ---------- 渲染 ----------
function render() {
  $("proj-title").textContent = DATA.title;
  $("provider").value = DATA.backend.provider;
  $("model").value = DATA.backend.model;
  $("chapter-chars").value = DATA.backend.chapter_chars;
  $("api-key").value = "";
  $("api-key").placeholder = DATA.backend.key_set ? "API Key 已设置 ✓" : "填 DeepSeek API Key";

  const fpMap = { default: "中性默认(还没懂你)", sample: "✓ 已学你的样本", inherit: "✓ 继承自另一本书" };
  $("fp-source").textContent = "指纹:" + (fpMap[DATA.fingerprint_source] || DATA.fingerprint_source);

  // 章节
  const ch = $("chapters"); ch.innerHTML = "";
  if (!DATA.chapters.length) ch.innerHTML = `<li class="hint">还没有章节</li>`;
  DATA.chapters.forEach((c) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>第${c.n}章</span>` +
      (c.edited ? `<span class="badge on">改过</span>` : ``) +
      (c.learned ? `<span class="badge on">已学</span>` : ``);
    li.onclick = () => openFile(`正文/第${c.n}章.md`, true, c.n, li);
    ch.appendChild(li);
  });
  $("btn-write-next").textContent = `写第${DATA.next_chapter}章 ▸`;

  fillList("brain", DATA.brain, true);
  fillList("skills", DATA.skills, false);
  fillList("agents", DATA.agents, false);
}
function fillList(id, items, editable) {
  const ul = $(id); ul.innerHTML = "";
  items.forEach((it) => {
    const li = document.createElement("li");
    if (it.rel.endsWith("写作指纹.md")) li.className = "fp";
    li.textContent = it.name;
    li.onclick = () => openFile(it.rel, editable, null, li);
    ul.appendChild(li);
  });
}

// ---------- 文件编辑 ----------
async function openFile(rel, editable, chapter, li) {
  document.querySelectorAll(".list li.active").forEach((x) => x.classList.remove("active"));
  if (li) li.classList.add("active");
  const d = await jreq("GET", `/api/file?root=${encodeURIComponent(DATA.root)}&rel=${encodeURIComponent(rel)}`);
  CUR = { rel, editable, chapter };
  $("editor").value = d.content;
  $("editor").readOnly = !editable;
  $("editor-path").textContent = rel + (editable ? "" : "(只读)");
  $("btn-save-file").classList.toggle("hidden", !editable);
  $("btn-learn").classList.toggle("hidden", chapter == null);
  $("editor-status").textContent = chapter != null
    ? "改完点【保存】,再点【学这章的手改】把你的风格喂给指纹。" : "";
}
async function saveFile() {
  if (!CUR) return;
  await jreq("PUT", "/api/file", { root: DATA.root, rel: CUR.rel, content: $("editor").value });
  toast("已保存");
  if (CUR.chapter != null) refresh();
}

// ---------- seed ----------
async function doSeed() {
  $("seed-error").textContent = "";
  const text = $("seed-text").value.trim();
  if (!text) { $("seed-error").textContent = "贴点你写的字再提炼。"; return; }
  $("seed-go").textContent = "提炼中…"; $("seed-go").disabled = true;
  try {
    DATA = await jreq("POST", "/api/seed", { root: DATA.root, text });
    render();
    $("seed-overlay").classList.add("hidden");
    $("seed-text").value = "";
    toast("写作指纹已提炼,它开始懂你了");
  } catch (e) { $("seed-error").textContent = e.message; }
  finally { $("seed-go").textContent = "提炼指纹"; $("seed-go").disabled = false; }
}

// ---------- learn ----------
async function learn(n) {
  try {
    const d = await jreq("POST", "/api/learn", { root: DATA.root, chapter: n });
    _lastLearnChapter = n;
    toast(`第${n}章手改已学,写后摘要已补进卡章纲`);
    await refresh();
    showLearnChanges(d.changes || { added: [], removed: [] });
  } catch (e) { toast(e.message, true); }
}
function showLearnChanges(changes) {
  const box = $("learn-changes"); box.innerHTML = "";
  const add = changes.added || [], rem = changes.removed || [];
  if (!add.length && !rem.length) {
    box.innerHTML = '<div class="hint">这次没有明显的规则变化。</div>';
  } else {
    rem.forEach((l) => { const e = document.createElement("div"); e.className = "chg rem"; e.textContent = "− " + l; box.appendChild(e); });
    add.forEach((l) => { const e = document.createElement("div"); e.className = "chg add"; e.textContent = "+ " + l; box.appendChild(e); });
  }
  $("learn-overlay").classList.remove("hidden");
}
async function revertLearn() {
  if (_lastLearnChapter == null) return;
  try {
    await jreq("POST", "/api/learn/revert", { root: DATA.root, chapter: _lastLearnChapter });
    toast("已撤销这次 learn,指纹还原");
    $("learn-overlay").classList.add("hidden");
    await refresh();
    openFile("外置大脑/写作指纹.md", true, null);
  } catch (e) { toast(e.message, true); }
}

// ---------- write(流式) ----------
let _wroteChapter = null;
async function writeChapter(n, force) {
  _wroteChapter = null;
  $("run-title").textContent = `正在写第 ${n} 章…`;
  $("agent-pills").innerHTML = "";
  $("run-log").innerHTML = "";
  $("run-stream").textContent = "";
  $("run-close").classList.add("hidden");
  $("run-force").classList.add("hidden");
  $("run-overlay").classList.remove("hidden");

  let resp;
  try {
    resp = await fetch("/api/write", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root: DATA.root, chapter: n, force }),
    });
  } catch (e) { logRun("连接失败:" + e.message, "err"); showRunClose(); return; }

  const ct = resp.headers.get("content-type") || "";
  if (!ct.includes("ndjson")) {
    const d = await resp.json().catch(() => ({}));
    logRun("✗ " + (d.error || `失败 (${resp.status})`), "err");
    if (resp.status === 409) {
      $("run-title").textContent = `第 ${n} 章已存在`;
      showRunForce(n);
    }
    showRunClose();
    return;
  }

  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) if (line.trim()) handleEvent(JSON.parse(line));
  }
  showRunClose();
}

function handleEvent(ev) {
  if (ev.type === "pipeline_start") {
    $("agent-pills").innerHTML = "";
    ev.roles.forEach((r) => {
      const p = document.createElement("div");
      p.className = "pill"; p.id = "pill-" + r; p.textContent = r;
      $("agent-pills").appendChild(p);
    });
  } else if (ev.type === "agent_start") {
    const p = $("pill-" + ev.role); if (p) p.classList.add("running");
    logRun(`▶ ${ev.role} …`);
    $("run-stream").textContent = "";  // 新一棒,清空实时稿区
  } else if (ev.type === "agent_chunk") {
    const s = $("run-stream");
    s.textContent += ev.delta;
    s.scrollTop = s.scrollHeight;  // 跟着写,自动滚到底
  } else if (ev.type === "agent_done") {
    const p = $("pill-" + ev.role); if (p) { p.classList.remove("running"); p.classList.add("done"); }
    logRun(`✓ ${ev.role} —— ${ev.produces}`, "ok");
  } else if (ev.type === "agent_skip") {
    const p = $("pill-" + ev.role); if (p) p.classList.add("done");
    logRun(`⏭ ${ev.role} —— 跳过(已完成、上游未变)`);
  } else if (ev.type === "edit_note") {
    logRun(`📝 本章改动留痕已存(.审稿留痕/)`);
  } else if (ev.type === "warn") {
    logRun("· " + ev.message);
  } else if (ev.type === "info") {
    logRun("▶ " + ev.message);
  } else if (ev.type === "chapter_done") {
    _wroteChapter = ev.chapter;
    logRun(`✓ 第${ev.chapter}章终稿 ${ev.chars} 字`, "ok");
    $("run-title").textContent = `第 ${ev.chapter} 章写完`;
  } else if (ev.type === "error") {
    logRun("✗ " + ev.message, "err");
  }
}
function logRun(text, cls) {
  const div = document.createElement("div");
  if (cls) div.className = cls;
  div.textContent = text;
  $("run-log").appendChild(div);
  $("run-log").scrollTop = $("run-log").scrollHeight;
}
function showRunClose() { $("run-close").classList.remove("hidden"); }
function showRunForce(n) {
  const b = $("run-force");
  b.onclick = () => writeChapter(n, true);
  b.classList.remove("hidden");
}
async function closeRun() {
  $("run-overlay").classList.add("hidden");
  await refresh();
  if (_wroteChapter != null) openFile(`正文/第${_wroteChapter}章.md`, true, _wroteChapter);
}

// ---------- 后端配置 ----------
async function saveBackend() {
  const key = $("api-key").value.trim();
  DATA = await jreq("PUT", "/api/config", {
    root: DATA.root, provider: $("provider").value, model: $("model").value,
    chapter_chars: parseInt($("chapter-chars").value) || 800,
    api_key: key || null,
  });
  toast(key ? "后端 + API Key 已保存" : "后端已保存");
  render();
}
