"use strict";

const $ = (id) => document.getElementById(id);
let DATA = null;            // 当前项目 state
let PROJECTS = null;        // 欢迎页项目库 registry
let CUR = null;             // 当前打开的文件 {rel, editable, chapter}
let _lastLearnChapter = null;  // 最近一次 learn 的章号(供撤销)
let _rewriteSel = null;        // 当前重写的选区 {start, end, span}
let _rewriteText = "";         // 当前重写候选
let _dirty = false;            // 编辑器是否有未保存改动
let _saveTimer = null;         // 自动保存 debounce
let _seedMode = "sample";      // seed 来源:sample | inherit

// ---------- 图标(iconfont Symbol)----------
// 单一改名处:HTML 里写 <span class="ico" data-ico="export">,JS 里用 icon("export")。
// 若你在 iconfont 项目里给图标起的 id 与右值不同,只改这张表即可(无需动各处调用)。
const IC = {
  sample: "icon-book",        key: "icon-key",
  theme: "icon-sun",          themeDark: "icon-moon",
  focus: "icon-focus",        focusExit: "icon-fullscreen-exit",
  chapters: "icon-doc",       writeNext: "icon-arrow-right",
  export: "icon-export",      backup: "icon-save",
  brain: "icon-brain",        fingerprint: "icon-fingerprint",  seed: "icon-magic",
  skills: "icon-tool",        agents: "icon-robot",
  search: "icon-search",      rewrite: "icon-scissors",         learn: "icon-trend-up",
  arrowUp: "icon-arrow-up",   arrowDown: "icon-arrow-down",      close: "icon-close",
  pin: "icon-pin",            edit: "icon-edit",
  outline: "icon-doc",        // 本章细纲(分镜)
  check: "icon-check",        cross: "icon-cross",
  redo: "icon-refresh",       warn: "icon-warning",
  play: "icon-play",          skip: "icon-skip",
  chevron: "icon-chevron-right",  // 折叠区展开/收起(展开时 CSS 转 90°)
  back: "icon-arrow-left",        // 回首页(退出当前书 / 换一本)
  history: "icon-history",        // 本章版本历史
  plus: "icon-plus",              // 插入空章
  trash: "icon-trash",            // 删除章节
};
function icon(name, cls) {
  const id = IC[name] || name;
  return `<svg class="icon${cls ? " " + cls : ""}" aria-hidden="true"><use xlink:href="#${id}"></use></svg>`;
}
// 给页面里所有 [data-ico] 占位符填上 svg(只填一次)
function hydrateIcons(root) {
  (root || document).querySelectorAll("[data-ico]").forEach((el) => {
    if (el._ico) return;
    el.insertAdjacentHTML("afterbegin", icon(el.dataset.ico));
    el._ico = true;
  });
}
function escHtml(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

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
  const b = $("btn-theme"); if (b) b.innerHTML = icon(t === "dark" ? "themeDark" : "theme");
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
  hydrateIcons();
  initTheme();
  bind();
  loadGenres();
  loadProjects().finally(() => {
    const saved = localStorage.getItem("loom_root");
    if (saved) openProject(saved, true);
  });
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
  const refreshProjects = $("btn-refresh-projects");
  if (refreshProjects) refreshProjects.onclick = loadProjects;
  $("btn-close-proj").onclick = () => { localStorage.removeItem("loom_root"); showWelcome(); };
  $("btn-theme").onclick = toggleTheme;
  $("btn-focus").onclick = toggleFocus;
  $("focus-exit").onclick = exitFocus;
  $("btn-doctor").onclick = runDoctor;
  $("doctor-close").onclick = () => $("doctor-overlay").classList.add("hidden");
  $("flow-close").onclick = () => $("flow-overlay").classList.add("hidden");
  $("flow-prompt").onclick = () => {
    const a = (DATA.agents || []).find((x) => x.name === _flowAgent);   // 留个口子:仍能去看/改提示词
    $("flow-overlay").classList.add("hidden");
    if (a) openFile(a.rel, false, null);
  };
  $("btn-save-backend").onclick = saveBackend;
  $("btn-save-global-key").onclick = saveGlobalKey;
  $("btn-probe").onclick = probeBackend;
  $("btn-fetch-models").onclick = fetchModels;
  $("model").onchange = onModelSelect;
  $("provider").onchange = () => {
    // 切供应商:从服务端下发的供应商表(DATA.backend.providers)派生默认模型 + 下拉预设 + base_url
    const p = $("provider").value;
    const spec = providerSpec(p);
    rebuildModelPresets(p);
    setModelValue(spec ? spec.default_model : "");
    if (spec && !spec.base_url_locked) $("base-url").value = $("base-url").value || spec.base_url || "";
    applyProviderUI(p);
  };
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
  $("btn-history").onclick = openHistory;
  $("history-close").onclick = () => $("history-overlay").classList.add("hidden");
  $("btn-sensitive").onclick = scanSensitive;
  $("btn-preview").onclick = () => CUR && setPreview(!CUR.preview);
  $("btn-outline").onclick = () => CUR && CUR.chapter != null && openOutline(CUR.chapter);
  $("btn-outline-regen").onclick = regenOutline;
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

  // 防丢稿:关窗/切走前保住未保存手改
  window.addEventListener("beforeunload", (e) => { if (_dirty) { e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("blur", () => { if (_dirty) autosave(); });
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
    setTimeout(startSampleTour, 350);  // 等 render + 布局稳定再起 T1 引导(只样例触发)
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
  loadProjects();
}
function enterProject(d) {
  DATA = d;
  localStorage.setItem("loom_root", d.root);
  $("welcome").classList.add("hidden");
  $("app").classList.remove("hidden");
  render();
  loadProjects();
}

async function loadProjects() {
  try {
    PROJECTS = await jreq("GET", "/api/projects");
    renderProjects();
    const parent = $("new-parent");
    if (PROJECTS.default_dir && parent && !parent.value.trim()) parent.value = PROJECTS.default_dir;
  } catch (e) {
    PROJECTS = null;
    renderProjects();
  }
}

function renderProjects() {
  const section = $("project-library");
  const list = $("project-list");
  if (!section || !list) return;

  const projects = PROJECTS && PROJECTS.projects ? PROJECTS.projects : {};
  const entries = Object.entries(projects).sort(([an, a], [bn, b]) => {
    const at = Date.parse((a && (a.last_open || a.created)) || "") || 0;
    const bt = Date.parse((b && (b.last_open || b.created)) || "") || 0;
    if (bt !== at) return bt - at;
    return an.localeCompare(bn);
  });

  list.innerHTML = "";
  section.classList.toggle("hidden", entries.length === 0);
  if (!entries.length) return;

  entries.forEach(([name, meta]) => {
    const info = meta || {};
    const path = info.path || "";
    const exists = info.exists !== false;

    const item = document.createElement("div");
    item.className = "project-item" + (exists ? "" : " missing");

    const open = document.createElement("button");
    open.type = "button";
    open.className = "project-open";
    open.title = path || name;
    open.disabled = !exists;
    open.innerHTML =
      `<span class="project-name"><span class="project-title">${escHtml(name)}</span>${exists ? "" : `<span class="project-missing">不存在</span>`}</span>` +
      `<span class="project-path">${escHtml(path)}</span>`;
    if (exists) open.onclick = () => openProject(path, false);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "project-remove ghost";
    remove.title = `从项目库移除: ${name}`;
    remove.innerHTML = icon("trash");
    remove.onclick = (e) => {
      e.stopPropagation();
      removeProject(name);
    };

    item.appendChild(open);
    item.appendChild(remove);
    list.appendChild(item);
  });
}

async function removeProject(name) {
  try {
    PROJECTS = await jreq("DELETE", `/api/projects/${encodeURIComponent(name)}`);
    renderProjects();
  } catch (e) {
    toast(e.message, true);
  }
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
      mark.className = "di-mark"; mark.innerHTML = icon(c.ok ? "check" : "cross");
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
function keySourceLabel() {
  const st = DATA && DATA.backend && DATA.backend.key_status;
  if (!st || !st.effective) return "未配置";
  const labels = {
    process: "系统环境 Key",
    project: "本项目 Key",
    global: "全局 Key",
    none: "未配置",
  };
  return labels[st.source] || "已配置 Key";
}

function render() {
  $("proj-title").textContent = DATA.title;
  $("provider").value = DATA.backend.provider;
  rebuildModelPresets(DATA.backend.provider);
  setModelValue(DATA.backend.model);
  $("base-url").value = DATA.backend.base_url || "";
  $("chapter-chars").value = DATA.backend.chapter_chars;
  $("api-key").value = "";
  const keyEffective = DATA.backend.key_status ? DATA.backend.key_status.effective : DATA.backend.key_set;
  $("api-key").placeholder = keyEffective ? keySourceLabel() + " 已生效" : "填 DeepSeek API Key";
  $("key-source").textContent = DATA.backend.provider === "deepseek" ? keySourceLabel() : "";
  applyProviderUI(DATA.backend.provider);   // 顺带按供应商设 key 框占位/显隐 base_url 与按钮

  const fpMap = {
    default: "中性默认 · 还没懂你",
    sample: icon("check") + " 已学你的样本",
    inherit: icon("check") + " 继承自另一本书",
  };
  $("fp-source").innerHTML = fpMap[DATA.fingerprint_source] || escHtml(DATA.fingerprint_source);

  // 章节
  const ch = $("chapters"); ch.innerHTML = "";
  if (!DATA.chapters.length) ch.innerHTML = `<li class="hint">还没有章节,点「写下一章」开始</li>`;
  DATA.chapters.forEach((c) => {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.className = "ch-label";
    label.innerHTML = `<span class="ch-no">第${c.n}章</span>` +
      (c.title ? `<span class="ch-title">${escHtml(c.title)}</span>` : ``) +
      (c.edited ? `<span class="badge on">改过</span>` : ``) +
      (c.learned ? `<span class="badge on">已学</span>` : ``);
    label.title = c.title ? `第${c.n}章 · ${c.title}` : `第${c.n}章`;
    label.onclick = () => openFile(`正文/第${c.n}章.md`, true, c.n, li);
    const actions = document.createElement("span");
    actions.className = "ch-actions";
    const act = (ic, title, fn) => {
      const b = document.createElement("button");
      b.className = "ch-act"; b.title = title; b.innerHTML = icon(ic);
      b.onclick = (e) => { e.stopPropagation(); fn(); };
      return b;
    };
    actions.appendChild(act("arrowUp", "上移一章", () => moveChapter(c.n, "up")));
    actions.appendChild(act("arrowDown", "下移一章", () => moveChapter(c.n, "down")));
    actions.appendChild(act("plus", `在第${c.n}章后插入空章`, () => insertAfter(c.n)));
    actions.appendChild(act("redo", `重写本章正文(按当前细纲覆盖第${c.n}章;想换结构先改/重新生成细纲)`, () => confirmRewriteChapter(c.n)));
    actions.appendChild(act("trash", `删除第${c.n}章`, () => deleteChapter(c.n)));
    li.appendChild(label); li.appendChild(actions);
    ch.appendChild(li);
  });
  $("btn-write-next").innerHTML = `写第${DATA.next_chapter}章 ` + icon("writeNext");

  fillList("brain", DATA.brain, true);
  fillSkills(DATA.skills);
  fillAgents(DATA.agents);
}

// 5 个 agent 不是「提示词文件」,是流水线上五个有人设的角色。点卡片 → 看整条流水线(不贴 Markdown)。
const AGENT_ORDER = ["设定师", "大纲师", "写手", "编辑", "润色师"];
const AGENTS_META = {
  "设定师": { slug: "loremaster", tag: "第一棒 · 立规矩", reads: "世界观 · 人物卡 · 方法论", produces: "本章设定锚点",        desc: "守世界观的人。开写前为这章圈好边界、钉死硬约束,绝不让设定穿帮。" },
  "大纲师": { slug: "outliner",   tag: "第二棒 · 搭骨架", reads: "卡章纲 · 故事引擎",       produces: "分镜细纲(场景骨头)", desc: "搭骨架的人。把这章拆成 3-6 场分镜,标好爆点和章末钩,让写手照着就能落字。" },
  "写手":   { slug: "writer",     tag: "第三棒 · 落字",   reads: "写作指纹 · 网文大神",     produces: "本章初稿",          desc: "真正落字的人。照着你的写作指纹写初稿——越写越像你,是这本书的灵魂。" },
  "编辑":   { slug: "editor",     tag: "第四棒 · 挑硬伤", reads: "评估自检",               produces: "本章改稿",          desc: "挑刺的人。盘爽点、钩子、OOC、设定漂移,问题当场改掉,只管内容硬伤。" },
  "润色师": { slug: "polisher",   tag: "第五棒 · 去AI味", reads: "去AI味 · 写作指纹",       produces: "本章终稿",          desc: "最后一道。擦掉 AI 腔与套话,却保留你的口头禅和怪句,让它读起来像真人。" },
};
// 头像:有图用 /agents/<slug>.jpg,没生成则退化成首字徽标
function agentAvatar(name, imgCls, fbCls) {
  const meta = AGENTS_META[name] || {};
  const initial = name.slice(0, 1);
  if (meta.slug) {
    const img = document.createElement("img");
    img.className = imgCls; img.src = `/agents/${meta.slug}.jpg`; img.alt = name; img.loading = "lazy";
    img.onerror = () => { const fb = document.createElement("span"); fb.className = fbCls; fb.textContent = initial; img.replaceWith(fb); };
    return img;
  }
  const fb = document.createElement("span"); fb.className = fbCls; fb.textContent = initial; return fb;
}
function fillAgents(items) {
  const ul = $("agents"); ul.innerHTML = "";
  items.forEach((it) => {
    const meta = AGENTS_META[it.name] || {};
    const li = document.createElement("li");
    li.className = "agent-card";
    li.appendChild(agentAvatar(it.name, "agent-ava", "agent-fallback"));
    const info = document.createElement("div"); info.className = "agent-info";
    const nm = document.createElement("div"); nm.className = "agent-name"; nm.textContent = it.name;
    if (meta.tag) { const t = document.createElement("span"); t.className = "agent-tag"; t.textContent = meta.tag; nm.appendChild(t); }
    const ds = document.createElement("div"); ds.className = "agent-desc"; ds.textContent = meta.desc || "";
    info.appendChild(nm); info.appendChild(ds);
    li.appendChild(info);
    li.onclick = () => openFlow(it.name);   // 点卡片 → 看全流程,而不是贴 Markdown
    ul.appendChild(li);
  });
}

// ---------- agent 全流程面板 ----------
let _flowAgent = null;
function openFlow(focusName) {
  const box = $("flow-stages"); box.innerHTML = "";
  AGENT_ORDER.forEach((name, i) => {
    if (i > 0) { const a = document.createElement("div"); a.className = "flow-arrow"; a.innerHTML = icon("chevron"); box.appendChild(a); }
    const meta = AGENTS_META[name] || {};
    const st = document.createElement("div");
    st.className = "flow-stage" + (name === focusName ? " on" : "");
    st.appendChild(agentAvatar(name, "flow-ava", "flow-fallback"));
    const body = document.createElement("div"); body.className = "flow-body";
    const nm = document.createElement("div"); nm.className = "flow-name";
    const b = document.createElement("b"); b.textContent = name; nm.appendChild(b);
    if (meta.tag) { const t = document.createElement("span"); t.className = "flow-tag"; t.textContent = meta.tag; nm.appendChild(t); }
    const ds = document.createElement("div"); ds.className = "flow-desc"; ds.textContent = meta.desc || "";
    const io = document.createElement("div"); io.className = "flow-io";
    io.innerHTML = `<span class="flow-reads">读 ${escHtml(meta.reads || "")}</span><span class="flow-prod">产出 ${escHtml(meta.produces || "")}</span>`;
    body.appendChild(nm); body.appendChild(ds); body.appendChild(io);
    st.appendChild(body);
    st.onclick = () => { box.querySelectorAll(".flow-stage").forEach((x) => x.classList.remove("on")); st.classList.add("on"); _flowAgent = name; _syncFlowPrompt(); };
    box.appendChild(st);
  });
  _flowAgent = focusName;
  _syncFlowPrompt();
  $("flow-overlay").classList.remove("hidden");
  const on = box.querySelector(".flow-stage.on"); if (on) on.scrollIntoView({ block: "nearest" });
}
function _syncFlowPrompt() {
  const btn = $("flow-prompt"); if (btn && _flowAgent) btn.textContent = `查看「${_flowAgent}」的提示词`;
}

// ---------- 通用引导浮层(skills 意图介绍 / 外置大脑空状态)----------
function showGuide({ title, bodyHtml, primary, ghost }) {
  $("guide-title").textContent = title;
  $("guide-body").innerHTML = bodyHtml;
  const pb = $("guide-primary"), gb = $("guide-ghost");
  const wire = (btn, spec) => {
    if (spec) { btn.classList.remove("hidden"); btn.textContent = spec.label;
      btn.onclick = () => { $("guide-overlay").classList.add("hidden"); spec.fn && spec.fn(); }; }
    else btn.classList.add("hidden");
  };
  wire(pb, primary); wire(gb, ghost);
  $("guide-overlay").classList.remove("hidden");
}

// skills 是给 Agent 看的「方法论手册」:点开先讲清是什么 / 哪一棒用,而不是糊一脸 Markdown
const SKILLS_META = {
  "世界观引擎": { who: "设定师", what: "怎么搭一个自洽、能长期写下去的世界观与力量体系。" },
  "故事引擎":   { who: "大纲师", what: "把『这章要完成什么』拆成有爆点、有钩子的分镜结构。" },
  "网文大神":   { who: "写手",   what: "网文落字手艺:画面代替形容词、对白带潜台词、短段落、章末留钩。" },
  "黄金开篇":   { who: "写手",   what: "只在第 1 章用:开篇怎么几句话就抓住读者。" },
  "评估自检":   { who: "编辑",   what: "章级自检清单:爽点够不够、钩子立没立、有没有 OOC / 设定漂移 / 拖节奏。" },
  "去AI味":     { who: "润色师", what: "怎么擦掉机器腔:套话头尾、空洞排比、黑名单词、被焊死的连接词。" },
  "金手指":     { who: "设定师", what: "金手指设计法:七字段、代价库、反制库,别让主角无敌到没冲突。" },
};
function fillSkills(items) {
  const ul = $("skills"); ul.innerHTML = "";
  items.forEach((it) => {
    const li = document.createElement("li");
    li.textContent = it.name;
    li.onclick = () => openSkillGuide(it.name, it.rel);
    ul.appendChild(li);
  });
}
function openSkillGuide(name, rel) {
  const m = SKILLS_META[name] || {};
  showGuide({
    title: `${name} · 方法论`,
    bodyHtml:
      `<p class="guide-lead">${escHtml(m.what || "这一棒 Agent 写作时参照的方法论。")}</p>` +
      (m.who ? `<div class="guide-who">${icon("robot", "guide-ico")} ${escHtml(m.who)}写作时会读它</div>` : "") +
      `<p class="hint">方法论是给 Agent 看的「手艺说明书」,平时不用管。想了解可查看全文。</p>`,
    primary: { label: "知道了" },
    ghost: { label: "查看方法论全文", fn: () => openFile(rel, false, null) },
  });
}

// 外置大脑:空 / 还没懂你 时给 onboarding,而不是甩一个空编辑器或中性默认文本
const BRAIN_GUIDE = {
  "世界观": "这本书的世界设定、力量体系、规则。设定师每章会读它,抽出本章能用的设定与绝不能违反的硬约束。",
  "人物卡": "主要人物的设定、关系、底线。防止写着写着人物 OOC、性格漂移。",
  "卡章纲": "整本书的分章规划,每章一句话任务。大纲师照它搭本章骨架;每章 learn 后这里还会自动补一条「AI 回顾」。",
  "写作指纹": "你的文风档案——句式、口头禅、节奏、禁用词。写手照它写,于是越写越像你。",
  "违禁词": "国内平台审核的敏感雷区清单 + 改写指引。写手/润色师参照它绕开红线;编辑器里「违禁词」按钮按它做本地粗筛。",
};
function maybeBrainGuide(rel, content) {
  if (!rel.startsWith("外置大脑/")) return;
  const empty = !content || !content.trim();
  const isFp = rel.endsWith("写作指纹.md");
  const neutralFp = isFp && /中性默认|还没.{0,4}懂你|还没学到你/.test(content);
  const isTemplate = !isFp && /占位示例|换成你自己的/.test(content);  // 还是出厂占位模板,也当「没填」引导
  if (!empty && !neutralFp && !isTemplate) return;
  const name = rel.split("/").pop().replace(/\.md$/, "");
  const desc = BRAIN_GUIDE[name] || "外置大脑的一部分,Agent 写作时会读它。";
  if (neutralFp) {
    showGuide({
      title: "写作指纹 · 还没懂你",
      bodyHtml: `<p class="guide-lead">${escHtml(desc)}</p>` +
        `<p class="hint">现在是中性默认。喂一段你写的字,或写几章手改后点「学这章的手改 learn」,它会慢慢长成你的样子——越写越像你。</p>`,
      primary: { label: "喂样本,让它懂我", fn: openSeed },
      ghost: { label: "先不管" },
    });
  } else {
    const draftable = ["世界观", "人物卡", "卡章纲"].includes(name);
    showGuide({
      title: `${name} · ${empty ? "还是空的" : "还是占位模板"}`,
      bodyHtml: `<p class="guide-lead">${escHtml(desc)}</p>` +
        (draftable
          ? `<p class="hint">不想从空白开始?写一句你的故事设定,让 AI 起草<b>世界观 / 人物卡 / 卡章纲</b>三件套,你再改成自己的。</p>` +
            `<textarea id="draft-idea" class="draft-idea" placeholder="一句话设定(可留空,按书名+题材发挥)。例:灵气复苏的都市,外卖小哥觉醒了能看见别人头顶任务的金手指。"></textarea>`
          : `<p class="hint">这是你来填的「外置大脑」。直接在编辑器里写就行,写得越具体,Agent 越不跑偏。</p>`),
      primary: draftable
        ? { label: "✨ 生成初稿(AI 起草,你再改)", fn: () => draftBrain(($("draft-idea") || {}).value || "") }
        : { label: "开始填写", fn: () => $("editor").focus() },
      ghost: { label: draftable ? "我自己填" : "知道了", fn: () => $("editor").focus() },
    });
  }
}
async function draftBrain(idea) {
  // 起草也要后端就绪:顺手保存后端(同写章),deepseek 仍缺 key 才拦
  try { await persistBackend(true); } catch (e) { toast("先配置好后端:" + e.message, true); return; }
  if (DATA.backend.provider === "deepseek" && !DATA.backend.key_set) {
    toast("先填 DeepSeek key(或把后端切到 Claude / Codex 免 key)再生成初稿", true);
    const k = $("api-key"); if (k) { k.focus(); k.classList.add("flash"); setTimeout(() => k.classList.remove("flash"), 1600); }
    return;
  }
  toast("AI 正在起草 世界观 / 人物卡 / 卡章纲…十几秒,稍候");
  try {
    const d = await jreq("POST", "/api/brain/draft", { root: DATA.root, idea: idea || "" });
    if (d.state) DATA = d.state;
    render();
    const w = d.written || [], s = d.skipped || [];
    toast(`已起草:${w.join(" / ") || "（无）"}${s.length ? `;${s.join("/")}你已填,没动` : ""} —— 打开看看,改成你的`);
    if (w.includes("世界观")) openFile("外置大脑/世界观.md", true, null);
  } catch (e) { toast(e.message, true); }
}

// ---------- 违禁词自检(本地粗筛,只提示不阻断) ----------
async function scanSensitive() {
  if (!CUR || CUR.chapter == null) return;
  try {
    const d = await jreq("POST", "/api/sensitive/scan", { root: DATA.root, text: $("editor").value });
    const hits = d.hits || [];
    if (!hits.length) {
      showGuide({
        title: "违禁词自检 · 没命中",
        bodyHtml: `<p class="guide-lead">本地粗筛没命中触发词。</p>` +
          `<p class="hint">这只兜低级漏网——平台审核偏严且不公开清单,终审仍建议人工把关。触发词可在「外置大脑 / 违禁词」里按题材增删。</p>`,
        primary: { label: "知道了" },
      });
      return;
    }
    const rows = hits.map((h) =>
      `<div class="sens-row"><span class="sens-word">${escHtml(h.word)}</span>` +
      `<span class="sens-cat">${escHtml(h.category)}</span><span class="sens-cnt">×${h.count}</span></div>`).join("");
    showGuide({
      title: `违禁词自检 · 命中 ${hits.length} 类`,
      bodyHtml: `<div class="sens-list">${rows}</div>` +
        `<p class="hint">只提示、不阻断。改写心法见「外置大脑 / 违禁词」:能架空就架空、能侧写就别直写、不给可复现的违法细节。</p>`,
      primary: { label: "知道了" },
      ghost: { label: "看改写指引", fn: () => openFile("外置大脑/违禁词.md", true, null) },
    });
  } catch (e) { toast(e.message, true); }
}
function fillList(id, items, editable) {
  const ul = $(id); ul.innerHTML = "";
  items.forEach((it) => {
    const li = document.createElement("li");
    const isFp = it.rel.endsWith("写作指纹.md");
    if (isFp) li.className = "fp";
    li.innerHTML = (isFp ? icon("fingerprint") : "") + escHtml(it.name);
    li.onclick = () => openFile(it.rel, editable, null, li);
    ul.appendChild(li);
  });
}

// ---------- Markdown 渲染(给普通用户看渲染版,不是一脸 # 和 -) ----------
function mdEsc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function mdInline(s) {
  return mdEsc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}
function mdToHtml(md) {
  const lines = (md || "").replace(/\r\n/g, "\n").split("\n");
  let html = "", i = 0, inUl = false, inOl = false;
  const close = () => { if (inUl) { html += "</ul>"; inUl = false; } if (inOl) { html += "</ol>"; inOl = false; } };
  while (i < lines.length) {
    const raw = lines[i], l = raw.trim();
    let m;
    if (!l) { close(); i++; continue; }
    if (m = l.match(/^(#{1,6})\s+(.*)$/)) { close(); const lv = m[1].length; html += `<h${lv}>${mdInline(m[2])}</h${lv}>`; i++; continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(l)) { close(); html += "<hr>"; i++; continue; }
    if (m = l.match(/^>\s?(.*)$/)) { close(); const q = []; while (i < lines.length && (m = lines[i].trim().match(/^>\s?(.*)$/))) { q.push(mdInline(m[1])); i++; } html += `<blockquote>${q.join("<br>")}</blockquote>`; continue; }
    if (m = l.match(/^[-*+]\s+(.*)$/)) { if (!inUl) { close(); html += "<ul>"; inUl = true; } const ind = raw.length - raw.trimStart().length; html += `<li${ind >= 2 ? ` style="margin-left:${Math.min(ind, 12) * 7}px"` : ""}>${mdInline(m[1])}</li>`; i++; continue; }
    if (m = l.match(/^\d+[.)]\s+(.*)$/)) { if (!inOl) { close(); html += "<ol>"; inOl = true; } html += `<li>${mdInline(m[1])}</li>`; i++; continue; }
    close(); const p = []; while (i < lines.length) { const t = lines[i].trim(); if (!t || /^(#{1,6}\s|>|[-*+]\s|\d+[.)]\s|-{3,}$|\*{3,}$|_{3,}$)/.test(t)) break; p.push(mdInline(t)); i++; } html += `<p>${p.join("<br>")}</p>`;
  }
  close();
  return html;
}
function setPreview(on) {
  if (!CUR) return;
  CUR.preview = on;
  const ed = $("editor"), pv = $("preview");
  if (on) { pv.innerHTML = mdToHtml(ed.value); pv.classList.remove("hidden"); ed.classList.add("hidden"); $("btn-preview").innerHTML = icon("edit") + " 编辑"; }
  else { pv.classList.add("hidden"); ed.classList.remove("hidden"); $("btn-preview").innerHTML = icon("edit") + " 预览"; }
}

// ---------- 文件编辑 ----------
async function openFile(rel, editable, chapter, li) {
  if (_dirty && CUR && CUR.editable) { try { await autosave(); } catch (e) { /* 落盘失败也别拦切换 */ } }  // 切文件前先保住手改
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
  $("btn-history").classList.toggle("hidden", chapter == null);
  $("btn-sensitive").classList.toggle("hidden", chapter == null);
  $("btn-learn").classList.toggle("hidden", chapter == null);
  $("btn-rewrite").classList.toggle("hidden", chapter == null);
  $("btn-outline").classList.toggle("hidden", chapter == null);  // 正文章节才给「本章细纲」入口
  $("btn-outline-regen").classList.add("hidden");                 // 默认藏,只在看细纲时由 openOutline 亮出
  $("btn-preview").classList.remove("hidden");
  setPreview(!rel.startsWith("正文/"));   // 外置大脑/skills/agents 默认渲染预览;正文/细纲 默认纯文本编辑
  $("status-note").textContent = chapter != null
    ? "改完会自动保存;再点【学这章的手改】把你的风格喂给指纹。" : "";
  updateWordCount();
  maybeBrainGuide(rel, d.content);   // 外置大脑空/未懂你 → 给 onboarding,不甩空编辑器
}
async function saveFile() {
  if (!CUR || !CUR.editable) return;
  clearTimeout(_saveTimer);
  await jreq("PUT", "/api/file", { root: DATA.root, rel: CUR.rel, content: $("editor").value });
  clearDirty();
  toast("已保存");
  $("status-note").innerHTML = "已保存 " + icon("check");
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
    if (CUR && CUR.rel === rel) { clearDirty(); $("status-note").innerHTML = "已自动保存 " + icon("check"); }
  } catch (e) { $("status-note").textContent = "自动保存失败:" + e.message; }
}

// ---------- 本章版本历史(覆盖前自动留快照,可回滚) ----------
async function openHistory() {
  if (!CUR || CUR.chapter == null) return;
  const box = $("history-list");
  box.innerHTML = `<div class="hint">读取中…</div>`;
  $("history-overlay").classList.remove("hidden");
  try {
    if (_dirty) await autosave();   // 先把当前手改落盘,免得回滚后丢
    const d = await jreq("GET", `/api/history?root=${encodeURIComponent(DATA.root)}&rel=${encodeURIComponent(CUR.rel)}`);
    renderHistory(d.versions || []);
  } catch (e) { box.innerHTML = `<div class="error">${e.message}</div>`; }
}
function _fmtStamp(id) {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/.exec(id);   // 尾部微秒忽略不显示
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}` : id;
}
function renderHistory(versions) {
  const box = $("history-list"); box.innerHTML = "";
  if (!versions.length) {
    box.innerHTML = `<div class="hint">还没有历史版本。保存或 AI 重写覆盖一次后,旧版会自动留在这里。</div>`;
    return;
  }
  versions.forEach((v) => {
    const el = document.createElement("div"); el.className = "hist-item";
    const head = document.createElement("div"); head.className = "hist-head";
    const meta = document.createElement("div"); meta.className = "hist-meta";
    meta.innerHTML = `<span class="hist-time">${_fmtStamp(v.id)}</span><span class="hist-chars">${v.chars} 字</span>`;
    const act = document.createElement("button"); act.className = "mini"; act.textContent = "回滚到这版";
    act.onclick = () => restoreHistory(v.id);
    head.appendChild(meta); head.appendChild(act);
    const prev = document.createElement("div"); prev.className = "hist-preview"; prev.textContent = v.preview || "";
    el.appendChild(head); el.appendChild(prev);
    box.appendChild(el);
  });
}
async function restoreHistory(id) {
  if (!CUR || CUR.chapter == null) return;
  if (!window.confirm("回滚会用这个历史版本覆盖当前正文(当前版本会先自动存一份,可再回滚回来)。确定?")) return;
  try {
    const d = await jreq("POST", "/api/history/restore", { root: DATA.root, rel: CUR.rel, id });
    $("editor").value = d.content;
    clearDirty(); updateWordCount();
    $("history-overlay").classList.add("hidden");
    toast("已回滚到该版本");
    if (CUR.chapter != null) refresh();
  } catch (e) { toast(e.message, true); }
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
    if (d.warn) toast(d.warn, true);   // 软提示:这次 learn 疑似把指纹磨短,可在弹窗里一键撤销
    await refresh();
    showLearnChanges(d.changes || { added: [], removed: [] }, extractRecap(d["卡章纲"] || "", n),
      { world: d["世界观补充"] || "", chars: d["人物卡补充"] || "" });
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
function showLearnChanges(changes, recap, supp) {
  const box = $("learn-changes"); box.innerHTML = "";
  const add = changes.added || [], rem = changes.removed || [];
  if (!add.length && !rem.length) {
    box.innerHTML = '<div class="hint">这次没有明显的规则变化。</div>';
  } else {
    if (rem.length) {
      const w = document.createElement("div");
      w.className = "learn-warn";
      w.innerHTML = `⚠️ 这次从你的写作指纹里 <b>删掉了 ${rem.length} 条</b>(下面红底划线的)。` +
        `若那是你之前 learn 攒下来的嗓音、不该被抹掉,点下面 <b>「撤销这次 learn」</b> 一键还原。`;
      box.appendChild(w);
      const h = document.createElement("div"); h.className = "sub-head"; h.textContent = "删掉的(原有规则被抹掉)"; box.appendChild(h);
      rem.forEach((l) => { const e = document.createElement("div"); e.className = "chg rem"; e.textContent = "− " + l; box.appendChild(e); });
    }
    if (add.length) {
      const h = document.createElement("div"); h.className = "sub-head"; h.textContent = "新增的(更像你)"; box.appendChild(h);
      add.forEach((l) => { const e = document.createElement("div"); e.className = "chg add"; e.textContent = "+ " + l; box.appendChild(e); });
    }
  }
  // 有删除时,撤掉「保留」的金色强调——让红色「撤销」成为唯一显眼按钮,
  // 别让作者顺手点金色「保留」把攒下来的嗓音丢了。
  $("learn-keep").classList.toggle("primary", rem.length === 0);
  const wrap = $("learn-recap-wrap");
  if (recap) { $("learn-recap").textContent = recap; wrap.classList.remove("hidden"); }
  else wrap.classList.add("hidden");
  // 外置大脑随章补充(世界观/人物卡):有就展示,让作者看见 loom 动了哪些设定(只追加、可改可删)
  const sw = $("learn-supp-wrap"); const sup = supp || {};
  const segs = [];
  if (sup.world) segs.push("【世界观】\n" + sup.world);
  if (sup.chars) segs.push("【人物卡】\n" + sup.chars);
  if (segs.length) { $("learn-supp").textContent = segs.join("\n\n"); sw.classList.remove("hidden"); }
  else sw.classList.add("hidden");
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

// ---------- 本章细纲(看 / 改 / 重新生成) ----------
async function openOutline(n) {
  const rel = `正文/.细纲/第${n}章.md`;
  // 旧章 / 还没生成过 → 细纲文件不存在;问一下要不要现在生成
  try {
    await jreq("GET", `/api/file?root=${encodeURIComponent(DATA.root)}&rel=${encodeURIComponent(rel)}`);
  } catch (e) {
    if (!confirm(`第${n}章还没有细纲(可能是旧章)。现在用「设定师→大纲师」生成一份?`)) return;
    if (await callRegen(n) == null) return;
  }
  await openFile(rel, true, null, null);   // 当普通可编辑文件打开(非正文章节,不出 learn/重写选中等)
  CUR.outline = n;
  $("editor-path").textContent = rel;
  $("status-note").textContent = `这是第${n}章的细纲(分镜)。改完它,重写本章(覆盖)就按你的细纲来;想要新方案点「重新生成细纲」。`;
  $("btn-outline-regen").classList.remove("hidden");
}
async function regenOutline() {
  if (!CUR || CUR.outline == null) return;
  if (!confirm(`重新生成第${CUR.outline}章细纲?当前细纲(含你的手改)会被覆盖。`)) return;
  const text = await callRegen(CUR.outline);
  if (text == null) return;
  $("editor").value = text; clearDirty(); toast("细纲已重新生成");
}
async function callRegen(n) {
  const btn = $("btn-outline-regen"); const old = btn.textContent;
  btn.disabled = true; btn.textContent = "生成中…(设定师→大纲师)";
  try {
    const d = await jreq("POST", "/api/outline/regen", { root: DATA.root, chapter: n });
    return d.outline;
  } catch (e) { toast(e.message, true); return null; }
  finally { btn.disabled = false; btn.textContent = old; }
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

// ---------- 章节管理(删 / 插 / 上下移)----------
async function chapterOp(url, body) {
  try {
    const d = await jreq("POST", url, body);
    // 章号变了:收掉当前打开的章节视图,避免指向错号
    CUR = null; $("editor").value = ""; $("editor-path").textContent = "选左边一个文件来看/改";
    ["btn-save-file", "btn-search", "btn-history", "btn-sensitive", "btn-learn", "btn-rewrite", "btn-outline", "btn-outline-regen", "btn-preview"].forEach((id) => $(id).classList.add("hidden"));
    document.querySelectorAll(".list li.active").forEach((x) => x.classList.remove("active"));
    updateWordCount();
    if (d.state) { DATA = d.state; render(); } else { await refresh(); }
    if (d.note) toast(d.note);
  } catch (e) { toast(e.message, true); }
}
function deleteChapter(n) {
  if (!window.confirm(`删除第 ${n} 章?\n它会移进回收站(正文/.回收站/,可手动恢复),后面的章节自动往前补号。`)) return;
  chapterOp("/api/chapter/delete", { root: DATA.root, n });
}
function insertAfter(n) { chapterOp("/api/chapter/insert", { root: DATA.root, n }); }
function moveChapter(n, direction) { chapterOp("/api/chapter/move", { root: DATA.root, n, direction }); }

// ---------- write(流式) ----------
let _wroteChapter = null;
async function writeChapter(n, force) {
  // 写章 = 顺手保存后端:不必先点「保存后端」,点写章就把当前后端表单(provider/model/字数/key)落盘
  try { await persistBackend(true); } catch (e) { toast("保存后端失败:" + e.message, true); return; }
  // 首跑防空转:没填 key/base_url 就别进面板转半天再报错,直接提示 + 高亮对应输入框
  const be = (DATA && DATA.backend) || {};
  const flash = (id) => { const k = $(id); if (k) { k.focus(); k.classList.add("flash"); setTimeout(() => k.classList.remove("flash"), 1600); } };
  if (be.provider === "deepseek" && !be.key_set) {
    toast("先在顶栏填 DeepSeek API Key(或把后端切到 Claude / Codex 免 key)再开写", true);
    flash("api-key"); return;
  }
  if (be.provider === "openai_compat" && (!be.base_url || !be.openai_compat_key_set)) {
    toast("自定义供应商要先填 base_url + API Key 再开写", true);
    flash(!be.base_url ? "base-url" : "api-key"); return;
  }
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
    logRun(d.error || `失败 (${resp.status})`, "err", "cross");
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
    logRun(`${ev.role} …`, null, "play");
    $("run-stream").textContent = "";  // 新一棒,清空实时稿区
  } else if (ev.type === "agent_chunk") {
    const s = $("run-stream");
    s.textContent += ev.delta;
    s.scrollTop = s.scrollHeight;  // 跟着写,自动滚到底
  } else if (ev.type === "agent_done") {
    const p = $("pill-" + ev.role); if (p) { p.classList.remove("running"); p.classList.add("done"); }
    logRun(`${ev.role} —— ${ev.produces}`, "ok", "check");
  } else if (ev.type === "agent_skip") {
    const p = $("pill-" + ev.role); if (p) p.classList.add("done");
    logRun(`${ev.role} —— 跳过(已完成、上游未变)`, null, "skip");
  } else if (ev.type === "gate_start") {
    const p = $("pill-" + ev.role); if (p) p.classList.add("running");
    logRun(`${ev.label}复审 · 第${ev.round}轮 …`, null, "search");
  } else if (ev.type === "gate_pass") {
    logRun(`${ev.label}通过(无硬伤)`, "ok", "check");
  } else if (ev.type === "gate_issues") {
    logRun(`发现 ${ev.issues.length} 处硬伤:`);
    ev.issues.forEach(it => logRun(
      `  · ${it["类别"]}:${it["问题"]}` + (it["证据"] ? `(证据:「${it["证据"]}」)` : "")));
  } else if (ev.type === "gate_revise") {
    logRun(`回炉重写中 …`, null, "redo");
    $("run-stream").textContent = "";  // 回炉稿重新流式
  } else if (ev.type === "gate_exhausted") {
    logRun(`${ev.label}跑满 ${ev.rounds} 轮仍有 ${ev.issues.length} 处残留 → 记入留痕,不阻断,继续`, null, "warn");
  } else if (ev.type === "edit_note") {
    logRun(`本章改动留痕已存(.审稿留痕/)`, null, "edit");
  } else if (ev.type === "sensitive") {
    const ws = (ev.hits || []).slice(0, 6).map((h) => h.word).join("、");
    logRun(`违禁词粗筛:命中 ${ev.count} 处(${ws}${(ev.hits || []).length > 6 ? "…" : ""})——只提示,不阻断,可在「违禁词」里改写`, null, "warn");
  } else if (ev.type === "warn") {
    logRun("· " + ev.message);
  } else if (ev.type === "info") {
    logRun(ev.message, null, "play");
  } else if (ev.type === "chapter_done") {
    _wroteChapter = ev.chapter;
    logRun(`第${ev.chapter}章终稿 ${ev.chars} 字`, "ok", "check");
    $("run-title").textContent = `第 ${ev.chapter} 章写完`;
  } else if (ev.type === "error") {
    logRun(ev.message, "err", "cross");
  }
}
function logRun(text, cls, ic) {
  const div = document.createElement("div");
  if (cls) div.className = cls;
  if (ic) div.innerHTML = icon(ic, "log-ico") + " " + escHtml(text);
  else div.textContent = text;
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
  if (_wroteChapter != null) {
    await openFile(`正文/第${_wroteChapter}章.md`, true, _wroteChapter);
    maybeCoachLearnLoop();  // T0:章稿落进编辑器那一刻,教 learn 闭环(只第一次)
  }
}

// ---------- 后端配置 ----------
function providerSpec(pid) {
  return ((DATA.backend && DATA.backend.providers) || []).find((p) => p.id === pid) || null;
}

// 用一组 {id,label} 重填模型【下拉】(末尾永远留一个「手动输入…」兜底,但默认是选、不是填)
function fillModelOptions(models) {
  const sel = $("model");
  sel.innerHTML = "";
  (models || []).forEach((m) => {
    const o = document.createElement("option");
    o.value = m.id; o.textContent = m.label || m.id || "（默认)";
    sel.appendChild(o);
  });
  const custom = document.createElement("option");
  custom.value = "__custom__"; custom.textContent = "✎ 手动输入…";
  sel.appendChild(custom);
}

// 切供应商时,用该供应商的预设建议重建下拉
function rebuildModelPresets(pid) {
  const spec = providerSpec(pid);
  fillModelOptions(spec ? spec.models : []);
}

// 选中某个模型:不在下拉里就先插一项再选(老配置/拉取结果都能正确回显);切到「手动输入」才露文本框
function setModelValue(model) {
  const sel = $("model"), custom = $("model-custom");
  model = model || "";
  if (model && ![...sel.options].some((o) => o.value === model)) {
    const o = document.createElement("option");
    o.value = model; o.textContent = model;
    sel.insertBefore(o, sel.querySelector('option[value="__custom__"]'));
  }
  sel.value = model;
  if (sel.selectedIndex < 0) sel.selectedIndex = 0;   // 空/没匹配上 → 落到第一项
  // 若落到了「手动输入…」(例:自定义供应商还没拉取预设)→ 露出文本框给用户填,别让他对着空下拉发愣
  if (sel.value === "__custom__") { custom.classList.remove("hidden"); custom.value = model && model !== "__custom__" ? model : ""; }
  else { custom.classList.add("hidden"); custom.value = ""; }
}

// 读当前选的模型(选了「手动输入」就读文本框)
function currentModelValue() {
  const sel = $("model");
  return sel.value === "__custom__" ? $("model-custom").value.trim() : sel.value;
}

// 下拉切到「手动输入…」→ 露出文本框聚焦;否则收起
function onModelSelect() {
  const custom = $("model-custom");
  if ($("model").value === "__custom__") { custom.classList.remove("hidden"); custom.focus(); }
  else custom.classList.add("hidden");
}

async function persistBackend(silent) {
  // 把顶栏后端表单(provider/model/base_url/字数/key)落盘;写章前会静默调一次,免得用户没点「保存后端」就开写
  const key = $("api-key").value.trim();
  const resp = await jreq("PUT", "/api/config", {
    root: DATA.root, provider: $("provider").value, model: currentModelValue(),
    base_url: $("base-url").value.trim() || null,
    chapter_chars: parseInt($("chapter-chars").value) || 800,
    api_key: key || null,
  });
  DATA = resp;
  if (!silent) toast(key ? "后端 + 本项目 Key 覆盖已保存" : "后端已保存");
  if (resp.model_warning) toast(resp.model_warning, true);   // 软提示(如把 v4-flash 填进 DeepSeek),不阻断
  render();
  if (CUR) updateWordCount();
}
async function saveBackend() { await persistBackend(false); }

async function saveGlobalKey() {
  const key = $("api-key").value.trim();
  if (!key) {
    toast("先填 DeepSeek API Key", true);
    $("api-key").focus();
    return;
  }
  try {
    DATA = await jreq("POST", "/api/settings/global-key", { root: DATA.root, api_key: key });
    toast("全局 DeepSeek Key 已保存");
    render();
    if (CUR) updateWordCount();
  } catch (e) {
    toast(e.message, true);
  }
}

// 「拉取可用模型」:OpenAI 兼容的实时打 GET /models,CLI 类返回预设。结果灌进下拉。
async function fetchModels() {
  const p = $("provider").value;
  const btn = $("btn-fetch-models");
  const old = btn.innerHTML; btn.disabled = true; btn.textContent = "拉取中…";
  try {
    const d = await jreq("POST", "/api/backend/models", {
      root: DATA.root, provider: p,
      base_url: $("base-url").value.trim() || null,
      api_key: $("api-key").value.trim() || null,
    });
    if (d.ok && d.models && d.models.length) {
      fillModelOptions(d.models);            // 实时列表灌进下拉,默认选第一个
      $("model").selectedIndex = 0;
      $("model-custom").classList.add("hidden");
      toast(d.message || `拉到 ${d.models.length} 个模型,下拉里选一个`);
      $("model").focus();
    } else {
      toast(d.message || "没拉到模型(检查 base_url / API Key)", true);
    }
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

// 按供应商显隐:key 框(deepseek/自定义)、base_url(仅自定义)、拉取模型按钮、检测连接(claude/codex)
function applyProviderUI(provider) {
  const spec = providerSpec(provider);
  const needsKey = spec ? spec.needs_key : (provider === "deepseek");
  const isDeepSeek = provider === "deepseek";
  const isCustom = provider === "openai_compat";
  const isCli = spec ? spec.kind === "cli" : (provider === "claude" || provider === "codex");
  $("api-key").classList.toggle("hidden", !needsKey);
  $("base-url").classList.toggle("hidden", !isCustom);
  $("btn-save-global-key").classList.toggle("hidden", !isDeepSeek);
  $("key-source").classList.toggle("hidden", !isDeepSeek);
  $("key-source").textContent = isDeepSeek ? keySourceLabel() : "";
  $("btn-fetch-models").classList.toggle("hidden", !(spec && spec.can_list_models));
  $("btn-probe").classList.toggle("hidden", !isCli);
  if (!needsKey || !isCli) { $("backend-status").textContent = ""; $("backend-status").className = "backend-status"; }
  if (needsKey) {
    const keySet = isCustom ? (DATA.backend && DATA.backend.openai_compat_key_set) : (DATA.backend && DATA.backend.key_set);
    $("api-key").placeholder = isDeepSeek
      ? (keySet ? keySourceLabel() + " 已生效" : "填 DeepSeek API Key")
      : (keySet ? "API Key 已设置" : "填这家供应商的 API Key");
  }
  if (isCustom && spec && spec.hint) $("base-url").title = spec.hint;
}
async function probeBackend() {
  const p = $("provider").value;
  const s = $("backend-status");
  s.className = "backend-status"; s.textContent = "检测中…";
  try {
    const d = await jreq("GET", `/api/backend/probe?provider=${encodeURIComponent(p)}`);
    s.className = "backend-status " + (d.ok ? "ok" : "bad");
    s.innerHTML = icon(d.ok ? "check" : "cross", "stat-ico") + " " + escHtml(d.message || "");
    s.title = d.hint || "";
    if (!d.ok && d.hint) toast(d.hint, true);   // 没装/没登录 → 把"该跑哪条命令"也弹出来
  } catch (e) {
    s.className = "backend-status bad";
    s.innerHTML = icon("cross", "stat-ico") + " " + escHtml(e.message);
  }
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
    c.push({ label: "回首页(换一本书)", keywords: "切换项目 换书 项目 退出 主页", run: () => { localStorage.removeItem("loom_root"); showWelcome(); } });
  }
  c.push({ label: "切换明暗主题", run: toggleTheme });
  _cmds = c;
}
function renderCmds(q) {
  const list = $("cmdk-list"); list.innerHTML = ""; _cmdSel = 0;
  _filtered = _cmds.filter((c) => (c.label + " " + (c.keywords || "")).toLowerCase().includes(q.toLowerCase()));
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
  if (_tourActive()) { endTour(); return true; }  // 引导开着时,Esc 先收引导
  if (!$("cmdk").classList.contains("hidden")) { closeCmdk(); return true; }
  const overlays = ["guide-overlay", "flow-overlay", "history-overlay", "rewrite-overlay", "seed-overlay", "learn-overlay", "doctor-overlay", "run-overlay"];
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

// ---------- 新手引导(onboarding):T0 就地提示 + T1 样例首跑 ----------
// 都用 localStorage 只显示一次。T0 不挡屏(JIT 气泡);T1 暗背景聚光引导样例。
const _seenOnce = (k) => localStorage.getItem(k) === "1";
const _markOnce = (k) => localStorage.setItem(k, "1");

// 把浮层放到目标附近:优先下方,放不下翻到上方;水平夹在视口内,箭头对准目标中心。
function _placeBubble(bubble, target, gap = 12) {
  const r = target.getBoundingClientRect();
  const bw = bubble.offsetWidth, bh = bubble.offsetHeight;
  let top = r.bottom + gap, below = true;
  if (top + bh > window.innerHeight - 8) { top = r.top - bh - gap; below = false; }
  let left = r.left + r.width / 2 - bw / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - bw - 8));
  bubble.style.top = Math.max(8, top) + "px";
  bubble.style.left = left + "px";
  bubble.classList.toggle("below", below);
  bubble.classList.toggle("above", !below);
  const arrowX = r.left + r.width / 2 - left;  // 箭头相对浮层左缘
  bubble.style.setProperty("--arrow-x", Math.max(16, Math.min(arrowX, bw - 16)) + "px");
}

// T0:写完一章、章稿落进编辑器那一刻,教 learn 闭环(只第一次)。
function maybeCoachLearnLoop() {
  if (_seenOnce("loom_coach_learnloop")) return;
  const btn = $("btn-learn");
  if (!btn || btn.classList.contains("hidden")) return;  // learn 按钮没出来就不提示
  _markOnce("loom_coach_learnloop");
  const pop = document.createElement("div");
  pop.className = "coach-pop";
  pop.innerHTML =
    `<div class="cp-body">这版是 <b>AI 写的,还不像你</b>。在编辑器里按你的习惯改几句,` +
    `再点上面的 <b>「学这章的手改」</b>——它只学<b>你的改动</b>、蒸馏进写作指纹,` +
    `于是<b>越写越像你</b>。这是 Loom 的灵魂。</div>` +
    `<div class="cp-foot"><button class="primary mini" id="cp-ok">懂了,去改稿</button></div>`;
  document.body.appendChild(pop);
  btn.classList.add("pulse-gold");
  _placeBubble(pop, btn);
  const reposition = () => _placeBubble(pop, btn);
  const close = () => { pop.remove(); btn.classList.remove("pulse-gold"); window.removeEventListener("resize", reposition); };
  window.addEventListener("resize", reposition);
  $("cp-ok").onclick = close;
  btn.addEventListener("click", close, { once: true });  // 真去点 learn 了也撤掉
}

// T1:打开样例书后,3 步聚光引导(只第一次)。
let _tourSteps = [], _tourI = 0, _tourEls = null, _spotTarget = null;
function startSampleTour() {
  if (_seenOnce("loom_tour_sample_v2")) return;
  if ($("app").classList.contains("hidden")) return;  // 没进项目就不引导
  _markOnce("loom_tour_sample_v2");
  _tourSteps = [
    { sel: "#brain-section", title: "外置大脑:它的记忆",
      body: "世界观 / 人物卡 / 卡章纲 / 写作指纹——5 个 Agent 读着这些写。每本书独有、会随你成长。样例已替你填好了。" },
    { sel: "#btn-write-next", title: "写下一章",
      body: "点这里:设定→大纲→写手→编辑→润色 五道工序依次接力,一章正文就织出来。样例已有第 1、2 章,你可以直接写第 3 章试试。" },
    { sel: "#fp-card", title: "越写越像你(灵魂)",
      body: "别急着满意 AI 的稿。在编辑器里按你的习惯手改,再点「学这章的手改」——它只学你的改动、蒸馏进这张写作指纹,于是越写越像你本人。" },
    { sel: "#btn-close-proj", title: "看够样例?回首页换自己的书",
      body: "右上角这个「回首页」就是出口:退出当前这本(样例),回到首页去新建或打开你自己的书。稿子都存在本地,样例随时还能再打开。" },
  ];
  _tourI = 0;
  _ensureTourEls();
  showTourStep();
}
function _ensureTourEls() {
  if (_tourEls) return;
  const back = document.createElement("div"); back.className = "tour-back";
  const spot = document.createElement("div"); spot.className = "tour-spot";
  const tip = document.createElement("div"); tip.className = "tour-tip";
  tip.innerHTML =
    `<div class="tt-title"></div><div class="tt-body"></div>` +
    `<div class="tt-foot"><span class="tt-dots"></span>` +
    `<span class="tt-btns"><button class="ghost mini tt-skip">跳过</button>` +
    `<button class="primary mini tt-next"></button></span></div>`;
  document.body.append(back, spot, tip);
  _tourEls = { back, spot, tip };
  tip.querySelector(".tt-skip").onclick = endTour;
  tip.querySelector(".tt-next").onclick = nextTourStep;
  back.onclick = (e) => e.stopPropagation();  // 吞掉点击,别穿透底层 UI
  window.addEventListener("resize", _repositionTour);
}
function showTourStep() {
  const step = _tourSteps[_tourI];
  const target = document.querySelector(step.sel);
  if (!target) return nextTourStep();  // 锚点缺失就跳过该步,别卡住
  const { back, spot, tip } = _tourEls;
  tip.querySelector(".tt-title").textContent = step.title;
  tip.querySelector(".tt-body").textContent = step.body;
  tip.querySelector(".tt-next").textContent = _tourI === _tourSteps.length - 1 ? "完成" : "下一步";
  const dots = tip.querySelector(".tt-dots"); dots.innerHTML = "";
  _tourSteps.forEach((_, i) => { const d = document.createElement("i"); d.className = "tt-dot" + (i === _tourI ? " on" : ""); dots.appendChild(d); });
  back.classList.add("on"); spot.classList.add("on"); tip.classList.add("on");
  _spotTarget = target;
  target.scrollIntoView({ block: "center", behavior: "smooth" });
  _repositionTour();
  setTimeout(_repositionTour, 80);  // 平滑滚动后再校准一次
}
function _repositionTour() {
  if (!_tourEls || !_spotTarget || !_tourEls.back.classList.contains("on")) return;
  const r = _spotTarget.getBoundingClientRect(), pad = 6, s = _tourEls.spot.style;
  s.top = (r.top - pad) + "px"; s.left = (r.left - pad) + "px";
  s.width = (r.width + pad * 2) + "px"; s.height = (r.height + pad * 2) + "px";
  _placeBubble(_tourEls.tip, _spotTarget, 14);
}
function nextTourStep() {
  if (_tourI >= _tourSteps.length - 1) return endTour();
  _tourI++; showTourStep();
}
function endTour() {
  if (!_tourEls) return;
  ["back", "spot", "tip"].forEach((k) => _tourEls[k].classList.remove("on"));
  _spotTarget = null;
}
function _tourActive() { return !!(_tourEls && _tourEls.back.classList.contains("on")); }
