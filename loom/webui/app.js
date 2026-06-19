"use strict";

const $ = (id) => document.getElementById(id);
let DATA = null;            // 当前项目 state
let CUR = null;             // 当前打开的文件 {rel, editable, chapter}
let _lastLearnChapter = null;  // 最近一次 learn 的章号(供撤销)
let _rewriteSel = null;        // 当前重写的选区 {start, end, span}
let _rewriteText = "";         // 当前重写候选
let _dirty = false;            // 编辑器是否有未保存改动
let _saveTimer = null;         // 自动保存 debounce
let _seedMode = "sample";      // seed 来源:sample | inherit

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
function countChars(s) { return (s.match(/\S/g) || []).length; }  // 非空白字符(含中文/标点)

// ---------- 主题(明暗) ----------
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("loom_theme", t);
  const b = $("btn-theme"); if (b) b.textContent = t === "dark" ? "☾" : "◐";
}
function initTheme() {
  const saved = localStorage.getItem("loom_theme");
  const t = saved || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(t);
}
function toggleTheme() {
  applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
}

// ---------- 专注模式 ----------
function toggleFocus() { document.body.classList.toggle("focus-mode"); }
function exitFocus() { document.body.classList.remove("focus-mode"); }

// ---------- 启动 ----------
window.addEventListener("DOMContentLoaded", () => {
  initTheme();
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
  $("btn-sample").onclick = openSample;
  $("btn-open").onclick = () => openProject($("open-path").value.trim(), false);
  $("btn-close-proj").onclick = () => { localStorage.removeItem("loom_root"); showWelcome(); };
  $("btn-theme").onclick = toggleTheme;
  $("btn-focus").onclick = toggleFocus;
  $("focus-exit").onclick = exitFocus;
  $("btn-doctor").onclick = runDoctor;
  $("doctor-close").onclick = () => $("doctor-overlay").classList.add("hidden");
  $("btn-save-backend").onclick = saveBackend;
  $("provider").onchange = () => { if ($("provider").value === "deepseek") $("model").value = "deepseek-chat"; };
  $("btn-write-next").onclick = () => writeChapter(DATA.next_chapter, false);
  $("btn-export").onclick = exportBook;
  $("btn-backup").onclick = backupBook;
  $("btn-seed").onclick = openSeed;
  $("seed-tab-sample").onclick = () => switchSeed("sample");
  $("seed-tab-inherit").onclick = () => switchSeed("inherit");
  $("seed-cancel").onclick = () => $("seed-overlay").classList.add("hidden");
  $("seed-go").onclick = doSeed;
  $("btn-save-file").onclick = saveFile;
  $("btn-learn").onclick = () => CUR && learn(CUR.chapter);
  $("btn-rewrite").onclick = openRewrite;
  $("rewrite-cancel").onclick = () => $("rewrite-overlay").classList.add("hidden");
  $("rewrite-go").onclick = doRewrite;
  $("rewrite-again").onclick = doRewrite;
  $("rewrite-apply").onclick = applyRewrite;
  $("learn-keep").onclick = () => { $("learn-overlay").classList.add("hidden"); openFile("外置大脑/写作指纹.md", true, null); };
  $("learn-revert").onclick = revertLearn;
  $("run-close").onclick = closeRun;

  // 编辑器:实时字数 + 自动保存 + 搜索联动
  $("editor").addEventListener("input", () => { updateWordCount(); markDirty(); if (_searchOn) runSearch(); });

  // 章内搜索
  $("btn-search").onclick = openSearch;
  $("search-close").onclick = closeSearch;
  $("search-next").onclick = () => gotoMatch(_mi + 1);
  $("search-prev").onclick = () => gotoMatch(_mi - 1);
  $("search-input").addEventListener("input", runSearch);
  $("search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); gotoMatch(e.shiftKey ? _mi - 1 : _mi + 1); }
    if (e.key === "Escape") { e.preventDefault(); closeSearch(); }
  });

  // 命令面板
  $("cmdk-input").addEventListener("input", () => renderCmds($("cmdk-input").value));
  $("cmdk-input").addEventListener("keydown", cmdkKey);

  // 全局快捷键
  document.addEventListener("keydown", globalKeys);
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
async function openSample() {
  $("welcome-error").textContent = "";
  try {
    const parent = $("new-parent").value.trim() || "~/Desktop";
    const d = await jreq("POST", "/api/sample/open", { parent });
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

// ---------- 备份 / 导出(纯本地) ----------
async function exportBook() {
  try {
    const d = await jreq("POST", "/api/export", { root: DATA.root });
    toast(`已导出 ${d.chapters} 章 → ${d.path}`);
  } catch (e) { toast(e.message, true); }
}
async function backupBook() {
  try {
    const d = await jreq("POST", "/api/backup", { root: DATA.root });
    toast(`已备份整本 → ${d.path}(拷到云盘/U盘才算真备份)`);
  } catch (e) { toast(e.message, true); }
}

// ---------- 启动自检(只读,面板呈现) ----------
async function runDoctor() {
  try {
    const d = await jreq("GET", `/api/doctor?root=${encodeURIComponent(DATA.root)}`);
    const list = $("doctor-list"); list.innerHTML = "";
    (d.checks || []).forEach((c) => {
      const el = document.createElement("div");
      el.className = "doctor-item " + (c.ok ? "ok" : "bad");
      const mark = document.createElement("span");
      mark.className = "di-mark"; mark.textContent = c.ok ? "✓" : "✗";
      const body = document.createElement("div");
      const name = document.createElement("div");
      name.className = "di-name"; name.textContent = c.name;
      body.appendChild(name);
      if (!c.ok) {
        const fix = document.createElement("div");
        fix.className = "di-fix";
        fix.textContent = `缺:${c.missing || "—"}　→　${c.fix || ""}`;
        body.appendChild(fix);
      }
      el.appendChild(mark); el.appendChild(body);
      list.appendChild(el);
    });
    $("doctor-overlay").classList.remove("hidden");
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

  const fpMap = { default: "中性默认 · 还没懂你", sample: "✓ 已学你的样本", inherit: "✓ 继承自另一本书" };
  $("fp-source").textContent = fpMap[DATA.fingerprint_source] || DATA.fingerprint_source;

  // 章节
  const ch = $("chapters"); ch.innerHTML = "";
  if (!DATA.chapters.length) ch.innerHTML = `<li class="hint">还没有章节,点「写下一章」开始</li>`;
  DATA.chapters.forEach((c) => {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.className = "ch-label";
    label.innerHTML = `<span>第${c.n}章</span>` +
      (c.edited ? `<span class="badge on">改过</span>` : ``) +
      (c.learned ? `<span class="badge on">已学</span>` : ``);
    label.onclick = () => openFile(`正文/第${c.n}章.md`, true, c.n, li);
    const actions = document.createElement("span");
    actions.className = "ch-actions";
    const rw = document.createElement("button");
    rw.className = "ch-act"; rw.title = `重写本章(AI 覆盖第${c.n}章)`; rw.textContent = "⟳";
    rw.onclick = (e) => { e.stopPropagation(); confirmRewriteChapter(c.n); };
    actions.appendChild(rw);
    li.appendChild(label); li.appendChild(actions);
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
  clearTimeout(_saveTimer); clearDirty(); closeSearch();
  document.querySelectorAll(".list li.active").forEach((x) => x.classList.remove("active"));
  if (li) li.classList.add("active");
  const d = await jreq("GET", `/api/file?root=${encodeURIComponent(DATA.root)}&rel=${encodeURIComponent(rel)}`);
  CUR = { rel, editable, chapter };
  $("editor").value = d.content;
  $("editor").readOnly = !editable;
  $("editor-path").textContent = rel + (editable ? "" : "(只读)");
  $("btn-save-file").classList.toggle("hidden", !editable);
  $("btn-search").classList.remove("hidden");
  $("btn-learn").classList.toggle("hidden", chapter == null);
  $("btn-rewrite").classList.toggle("hidden", chapter == null);
  $("status-note").textContent = chapter != null
    ? "改完会自动保存;再点【学这章的手改】把你的风格喂给指纹。" : "";
  updateWordCount();
}
async function saveFile() {
  if (!CUR || !CUR.editable) return;
  clearTimeout(_saveTimer);
  await jreq("PUT", "/api/file", { root: DATA.root, rel: CUR.rel, content: $("editor").value });
  clearDirty();
  toast("已保存");
  $("status-note").textContent = "已保存 ✓";
  if (CUR.chapter != null) refresh();
}

// ---------- 字数 / 自动保存 / 脏标记 ----------
function updateWordCount() {
  const wc = $("wordcount"), prog = $("progress"), bar = $("progress-bar");
  if (!CUR) { wc.textContent = ""; prog.classList.add("hidden"); return; }
  const n = countChars($("editor").value);
  if (CUR.chapter != null && DATA && DATA.backend.chapter_chars) {
    const target = DATA.backend.chapter_chars;
    wc.innerHTML = `字数 <b>${n.toLocaleString()}</b> · 目标 ${target.toLocaleString()}`;
    prog.classList.remove("hidden");
    bar.style.width = Math.min(100, (n / target) * 100) + "%";
    bar.classList.toggle("done", n >= target);
  } else {
    wc.innerHTML = `字数 <b>${n.toLocaleString()}</b>`;
    prog.classList.add("hidden");
  }
}
function markDirty() {
  if (!CUR || !CUR.editable) return;
  _dirty = true;
  document.querySelector(".path").classList.add("dirty");
  $("status-note").textContent = "未保存…";
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(autosave, 900);
}
function clearDirty() {
  _dirty = false;
  document.querySelector(".path").classList.remove("dirty");
}
async function autosave() {
  if (!CUR || !CUR.editable || !_dirty) return;
  const rel = CUR.rel, content = $("editor").value;
  try {
    await jreq("PUT", "/api/file", { root: DATA.root, rel, content });
    if (CUR && CUR.rel === rel) { clearDirty(); $("status-note").textContent = "已自动保存 ✓"; }
  } catch (e) { $("status-note").textContent = "自动保存失败:" + e.message; }
}

// ---------- seed ----------
function openSeed() {
  $("seed-error").textContent = "";
  switchSeed("sample");
  $("seed-overlay").classList.remove("hidden");
}
function switchSeed(m) {
  _seedMode = m;
  $("seed-tab-sample").classList.toggle("on", m === "sample");
  $("seed-tab-inherit").classList.toggle("on", m === "inherit");
  $("seed-pane-sample").classList.toggle("hidden", m !== "sample");
  $("seed-pane-inherit").classList.toggle("hidden", m !== "inherit");
}
async function doSeed() {
  $("seed-error").textContent = "";
  const body = { root: DATA.root };
  if (_seedMode === "inherit") {
    const p = $("seed-inherit-path").value.trim();
    if (!p) { $("seed-error").textContent = "填那本书的写作指纹文件路径。"; return; }
    body.inherit = p;
  } else {
    const text = $("seed-text").value.trim();
    if (!text) { $("seed-error").textContent = "贴点你写的字再提炼。"; return; }
    body.text = text;
  }
  $("seed-go").textContent = "提炼中…"; $("seed-go").disabled = true;
  try {
    DATA = await jreq("POST", "/api/seed", body);
    render();
    $("seed-overlay").classList.add("hidden");
    $("seed-text").value = "";
    toast("写作指纹已就位,它开始懂你了");
  } catch (e) { $("seed-error").textContent = e.message; }
  finally { $("seed-go").textContent = "提炼指纹"; $("seed-go").disabled = false; }
}

// ---------- learn ----------
async function learn(n) {
  try {
    if (CUR && CUR.chapter === n && _dirty) await autosave();  // 先把手改落盘,别让 learn 学到旧稿
    const d = await jreq("POST", "/api/learn", { root: DATA.root, chapter: n });
    _lastLearnChapter = n;
    toast(`第${n}章手改已学,写后摘要已补进卡章纲`);
    await refresh();
    showLearnChanges(d.changes || { added: [], removed: [] }, extractRecap(d["卡章纲"] || "", n));
  } catch (e) { toast(e.message, true); }
}
function extractRecap(kataGang, n) {
  const lines = kataGang.split("\n");
  const head = new RegExp(`^\\s*-\\s*第\\s*${n}\\s*章`);
  const nextCh = /^\s*-\s*第\s*\d+\s*章/;
  let i = lines.findIndex((l) => head.test(l));
  if (i < 0) return "";
  const block = [];
  for (let j = i + 1; j < lines.length; j++) {
    if (nextCh.test(lines[j])) break;          // 到下一章为止
    if (lines[j].trim() === "" && !block.length) continue;
    block.push(lines[j]);
  }
  const joined = block.join("\n");
  const k = joined.indexOf("[AI回顾]");
  return k >= 0 ? joined.slice(k).replace(/^\s+/, "").replace(/\n\s+/g, "\n").trim() : "";
}
function showLearnChanges(changes, recap) {
  const box = $("learn-changes"); box.innerHTML = "";
  const add = changes.added || [], rem = changes.removed || [];
  if (!add.length && !rem.length) {
    box.innerHTML = '<div class="hint">这次没有明显的规则变化。</div>';
  } else {
    rem.forEach((l) => { const e = document.createElement("div"); e.className = "chg rem"; e.textContent = "− " + l; box.appendChild(e); });
    add.forEach((l) => { const e = document.createElement("div"); e.className = "chg add"; e.textContent = "+ " + l; box.appendChild(e); });
  }
  const wrap = $("learn-recap-wrap");
  if (recap) { $("learn-recap").textContent = recap; wrap.classList.remove("hidden"); }
  else wrap.classList.add("hidden");
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

// ---------- 局部重写 ----------
function openRewrite() {
  if (!CUR || CUR.chapter == null) return;
  const ed = $("editor");
  const start = ed.selectionStart, end = ed.selectionEnd;
  const span = ed.value.substring(start, end);
  if (!span.trim()) { toast("先在正文里选中要重写的一段", true); return; }
  _rewriteSel = { start, end, span };
  _rewriteText = "";
  $("rewrite-src").textContent = span;
  $("rewrite-instruction").value = "";
  $("rewrite-error").textContent = "";
  $("rewrite-result").textContent = "";
  $("rewrite-result").classList.add("hidden");
  $("rewrite-go").classList.remove("hidden");
  $("rewrite-again").classList.add("hidden");
  $("rewrite-apply").classList.add("hidden");
  $("rewrite-overlay").classList.remove("hidden");
}
async function doRewrite() {
  if (!_rewriteSel) return;
  $("rewrite-error").textContent = "";
  $("rewrite-go").disabled = $("rewrite-again").disabled = true;
  try {
    const d = await jreq("POST", "/api/rewrite", {
      root: DATA.root, chapter: CUR.chapter,
      full_text: $("editor").value, span: _rewriteSel.span,
      instruction: $("rewrite-instruction").value.trim(),
    });
    _rewriteText = d.rewritten;
    $("rewrite-result").textContent = d.rewritten;
    $("rewrite-result").classList.remove("hidden");
    $("rewrite-go").classList.add("hidden");
    $("rewrite-again").classList.remove("hidden");
    $("rewrite-apply").classList.remove("hidden");
  } catch (e) { $("rewrite-error").textContent = e.message; }
  finally { $("rewrite-go").disabled = $("rewrite-again").disabled = false; }
}
async function applyRewrite() {
  if (!_rewriteSel || !_rewriteText) return;
  const ed = $("editor");
  const content = ed.value.substring(0, _rewriteSel.start) + _rewriteText + ed.value.substring(_rewriteSel.end);
  try {
    await jreq("POST", "/api/rewrite/apply", {
      root: DATA.root, chapter: CUR.chapter, content,
      old_span: _rewriteSel.span, new_span: _rewriteText,
    });
    ed.value = content;
    clearDirty();
    updateWordCount();
    $("rewrite-overlay").classList.add("hidden");
    toast("已替换选中段");
    await refresh();
  } catch (e) { $("rewrite-error").textContent = e.message; }
}

// ---------- 重写已存在章节(覆盖逃生门) ----------
function confirmRewriteChapter(n) {
  const ok = window.confirm(`重写会用 AI 重新生成并【覆盖】第 ${n} 章的现有正文。\n建议先「备份整本」。确定继续?`);
  if (ok) writeChapter(n, true);
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
    const box = $("agent-pills"); box.innerHTML = "";
    ev.roles.forEach((r, i) => {
      if (i > 0) { const c = document.createElement("div"); c.className = "connector"; box.appendChild(c); }
      const p = document.createElement("div");
      p.className = "pill"; p.id = "pill-" + r; p.textContent = r;
      box.appendChild(p);
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
  if (CUR) updateWordCount();
}

// ---------- 章内搜索 ----------
let _searchOn = false, _matches = [], _mi = 0;
function openSearch() {
  if (!CUR) return;
  _searchOn = true;
  $("search-bar").classList.add("on");
  $("search-input").focus(); $("search-input").select();
  runSearch();
}
function closeSearch() {
  _searchOn = false;
  $("search-bar").classList.remove("on");
  _matches = []; $("search-count").textContent = "";
}
function runSearch() {
  const q = $("search-input").value;
  const text = $("editor").value;
  _matches = [];
  if (q) {
    const hay = text.toLowerCase(), needle = q.toLowerCase();
    let idx = hay.indexOf(needle, 0);
    while (idx !== -1) { _matches.push(idx); idx = hay.indexOf(needle, idx + Math.max(1, needle.length)); }
  }
  _mi = 0;
  updateSearchCount();
  if (_matches.length) gotoMatch(0);
}
function updateSearchCount() {
  const c = $("search-count");
  c.textContent = _matches.length ? `${_mi + 1}/${_matches.length}`
    : ($("search-input").value ? "无结果" : "");
}
function gotoMatch(i) {
  if (!_matches.length) return;
  _mi = (i + _matches.length) % _matches.length;
  const start = _matches[_mi], q = $("search-input").value;
  const ed = $("editor");
  ed.focus();
  ed.setSelectionRange(start, start + q.length);
  // 让选区滚进视野:按行号近似定位
  const lineNo = ed.value.slice(0, start).split("\n").length - 1;
  const lh = parseFloat(getComputedStyle(ed).lineHeight) || 32;
  ed.scrollTop = Math.max(0, lineNo * lh - ed.clientHeight / 2);
  updateSearchCount();
}

// ---------- 命令面板 ⌘K ----------
let _cmds = [], _filtered = [], _cmdSel = 0;
function openCmdk() {
  buildCmds();
  $("cmdk-input").value = "";
  renderCmds("");
  $("cmdk").classList.remove("hidden");
  $("cmdk-input").focus();
}
function closeCmdk() { $("cmdk").classList.add("hidden"); }
function buildCmds() {
  const c = [];
  const inProj = !$("app").classList.contains("hidden");
  if (inProj && DATA) {
    c.push({ label: `写下一章(第${DATA.next_chapter}章)`, key: "⌘↵", run: () => writeChapter(DATA.next_chapter, false) });
    if (CUR && CUR.chapter != null) {
      c.push({ label: `重写本章(覆盖第${CUR.chapter}章)`, run: () => confirmRewriteChapter(CUR.chapter) });
      c.push({ label: "学这章的手改 learn", run: () => learn(CUR.chapter) });
    }
    if (CUR && CUR.editable) c.push({ label: "保存", key: "⌘S", run: saveFile });
    if (CUR) c.push({ label: "章内搜索", key: "⌘F", run: openSearch });
    c.push({ label: "喂样本 / 继承指纹 seed", run: openSeed });
    c.push({ label: "导出全书", run: exportBook });
    c.push({ label: "备份整本", run: backupBook });
    c.push({ label: "环境自检 doctor", run: runDoctor });
    c.push({ label: "专注模式", key: "⌘.", run: toggleFocus });
    c.push({ label: "切换项目", run: () => { localStorage.removeItem("loom_root"); showWelcome(); } });
  }
  c.push({ label: "切换明暗主题", run: toggleTheme });
  _cmds = c;
}
function renderCmds(q) {
  const list = $("cmdk-list"); list.innerHTML = ""; _cmdSel = 0;
  _filtered = _cmds.filter((c) => c.label.toLowerCase().includes(q.toLowerCase()));
  if (!_filtered.length) { list.innerHTML = `<div class="cmdk-empty">没有匹配的命令</div>`; return; }
  _filtered.forEach((c, i) => {
    const el = document.createElement("div");
    el.className = "cmdk-item" + (i === 0 ? " sel" : "");
    el.dataset.i = i;
    const lab = document.createElement("span"); lab.textContent = c.label; el.appendChild(lab);
    if (c.key) { const k = document.createElement("span"); k.className = "ci-key"; k.textContent = c.key; el.appendChild(k); }
    el.onclick = () => { closeCmdk(); c.run(); };
    list.appendChild(el);
  });
}
function cmdkKey(e) {
  if (e.key === "ArrowDown") { e.preventDefault(); moveCmdSel(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveCmdSel(-1); }
  else if (e.key === "Enter") { e.preventDefault(); const c = _filtered[_cmdSel]; if (c) { closeCmdk(); c.run(); } }
  else if (e.key === "Escape") { e.preventDefault(); closeCmdk(); }
}
function moveCmdSel(d) {
  if (!_filtered.length) return;
  _cmdSel = (_cmdSel + d + _filtered.length) % _filtered.length;
  [...$("cmdk-list").children].forEach((el, i) => el.classList.toggle("sel", i === _cmdSel));
  const sel = $("cmdk-list").children[_cmdSel];
  if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest" });
}

// ---------- 全局快捷键 ----------
function anyOverlayOpen() {
  return [...document.querySelectorAll(".overlay")].some((o) => !o.classList.contains("hidden"));
}
function closeTopOverlay() {
  if (!$("cmdk").classList.contains("hidden")) { closeCmdk(); return true; }
  const overlays = ["rewrite-overlay", "seed-overlay", "learn-overlay", "doctor-overlay", "run-overlay"];
  for (const id of overlays) {
    if (!$(id).classList.contains("hidden")) {
      if (id === "run-overlay" && $("run-close").classList.contains("hidden")) return true; // 写作中,别误关
      $(id).classList.add("hidden");
      return true;
    }
  }
  if (_searchOn) { closeSearch(); return true; }
  if (document.body.classList.contains("focus-mode")) { exitFocus(); return true; }
  return false;
}
function globalKeys(e) {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); $("cmdk").classList.contains("hidden") ? openCmdk() : closeCmdk(); return; }
  if (e.key === "Escape") { if (closeTopOverlay()) e.preventDefault(); return; }
  // 命令面板开着时,其余快捷键交给它自己处理
  if (!$("cmdk").classList.contains("hidden")) return;
  // 以下仅在已进入项目时生效
  if ($("app").classList.contains("hidden")) return;
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); if (CUR && CUR.editable) saveFile(); return; }
  if (mod && e.key === "Enter") { e.preventDefault(); if (!anyOverlayOpen() && DATA) writeChapter(DATA.next_chapter, false); return; }
  if (mod && e.key.toLowerCase() === "f") { e.preventDefault(); if (CUR) openSearch(); return; }
  if (mod && e.key === ".") { e.preventDefault(); toggleFocus(); return; }
}
