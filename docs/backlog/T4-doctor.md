# T4-doctor · 极简 doctor 启动自检(loom doctor 子命令 + /api/doctor + WebUI 自检按钮)
- **类型**: code　**工作量**: small　**批次**: 批次1 · 零风险即做(纯内容/隔离小代码)
- **依赖**: 无
- **涉及文件**:
  - `/Users/chambers/Desktop/Project/playground/Loom/loom/doctor.py`
  - `/Users/chambers/Desktop/Project/playground/Loom/loom/cli.py`
  - `/Users/chambers/Desktop/Project/playground/Loom/loom/server.py`
  - `/Users/chambers/Desktop/Project/playground/Loom/loom/webui/app.js`
  - `/Users/chambers/Desktop/Project/playground/Loom/loom/webui/index.html`

## 问题(Loom 现状)

Loom 现在没有任何启动自检。环境缺东西只能等到调用后端时才炸,且分散在各处无统一入口:
- DEEPSEEK key 缺失:只有真正调 DeepSeek 时才报(loom/backends.py:30-36 抛 LoomBackendError),CLI 要走到 write 才知道。
- provider=claude 但没装 `claude` 命令:要等 ClaudeCodeBackend.__init__ 才报(loom/backends.py:64-67)。
- provider=deepseek 但没装 openai 库:延迟 import 在 DeepSeekBackend.complete 里(loom/backends.py:38),要写到一半才炸。
- loom.toml 格式坏:只在 load_config 抛 ValueError(loom/config.py:36-37),没有一个轻量入口提前告诉你。
- 5 个 agent 文件(loom/templates/agents/{设定师,大纲师,写手,编辑,润色师}.md)或外置大脑四件套(外置大脑/{世界观,人物卡,卡章纲,写作指纹}.md)被误删:目前没有任何地方校验。run_pipeline 读不到 agent 文件会直接炸;server.py 的 _state() 只是机械列出文件名,从不检查它们是否真的存在(loom/server.py:56-58)。注意:写作指纹.md 由 scaffold 在 init 时落盘(loom/scaffold.py:30),不在 templates 里,所以四件套要按 server.py:31 的 _BRAIN 清单去项目根实际 stat。

缺一个"一眼看清缺什么→怎么补"的极简自检:CLI 一条 `loom doctor`、WebUI 一个"自检"按钮、server 一个只读 /api/doctor。

## 从 webnovel-writer 借什么 / 丢什么

借鉴 /tmp/webnovel-writer/webnovel-writer/scripts/data_modules/doctor.py,只取它的"列项自检"骨架思想:
- 每个检查项是一个结构化 dict,带 status(ok/error)+ message + actual(缺什么)+ repair(怎么补)。见 WW doctor.py:41-63 的 _check() 工厂,和 _file_checks(:129-180)里"required file 存在性 → exists/missing → repair 一句话"的模式。
- 顶层聚合:build_doctor_report 收集所有 check、算出 ok = not blocking(WW doctor.py:516-530)。
- 文本渲染:format_doctor_report 只打印非 ok 的项,每项 message/actual/repair 一行(WW doctor.py:533-559)。Loom 照"只显示问题项 + 每项一行缺什么怎么补"。
- 依赖库存在性检查复用 importlib.util.find_spec(WW doctor.py:389-402)检测 openai。
- 退出码语义:doctor 主流程 ok→0 否则→1(WW doctor.py:572)。

明确丢弃(全是 WW 的重基础设施/解析层,违背 Loom 红线③ 极简本地):
- _sqlite_checks(:235-289)整段——Loom 不引入 SQLite/index_db/vector_db。
- _rag_checks(:292-311)、embed/rerank key——Loom 无 RAG。
- _projection_log_checks(:314-373)、projection_run_*——Loom 无投影链。
- _dashboard_checks(:420-448)、--deep 模式、前端 dist 校验——Loom 是 PyWebView 单页,无构建产物。
- ProjectPhaseSnapshot/resolve_project_phase/phase 感知/_expected_profile(:87-102,458)——Loom 无 phase 状态机,刻意极简。
- contract_files_for_chapter/story_runtime_health/story-system 合同(:31,164-179,481)——Loom 无主链合同层。
- schema_version、severity 三级(blocker/warning/info)、preflight——Loom 只要 ok/missing 二态 + 一行修复。argparse main() 也不要(Loom 用 typer)。

## Loom 落地设计

新增 loom/doctor.py(约 90 行,无外部依赖,核心是纯函数 run_checks(root)->list[Check]):

1) 数据结构与核心函数
- @dataclass Check: name:str, ok:bool, missing:str, fix:str(missing/fix 仅 ok=False 时填)。
- def run_checks(root: Path) -> list[Check]: 顺序产出下列检查,全部用 try/except 包成 Check,绝不抛栈。
  a. loom.toml 可解析:复用 config.load_config(root)。捕获 ValueError/FileNotFoundError → Check(ok=False, missing="loom.toml 缺失或格式错误", fix="检查 loom.toml 是否存在且为合法 TOML;或重新 loom init")。解析成功后拿到 cfg 给后续用。
  b. provider 凭据:cfg.provider=="deepseek" → 检查 config.key_is_set(root)(loom/config.py:59-66,读 .env 的 DEEPSEEK_API_KEY)。缺→fix=".env 里加一行 DEEPSEEK_API_KEY=sk-你的key"。
  c. provider 对应命令/库:deepseek→importlib.util.find_spec("openai")(fix="pip install openai");claude→shutil.which("claude")(fix="装 Claude Code 并确保 claude 在 PATH");codex→shutil.which("codex")(fix="codex 后端 v0.1 未接,先用 deepseek/claude")。
  d. 5 个 agent 文件齐:for n in ["设定师","大纲师","写手","编辑","润色师"]: (root/"agents"/f"{n}.md").is_file();缺→fix=f"补回 agents/{n}.md,或 loom init 新项目对照模板"。
  e. 外置大脑四件套在:for n in ["世界观","人物卡","卡章纲","写作指纹"]: (root/"外置大脑"/f"{n}.md").is_file();缺→fix(写作指纹特判:"loom seed 重新生成或从备份恢复";其余:"人维护文件,手动补回内容")。
- 复用 server.py:31-33 的 _BRAIN/_AGENTS 清单避免硬编码漂移:把这两个列表上提到 doctor.py 里定义为 BRAIN_FILES/AGENT_FILES,server.py 改为 from .doctor import BRAIN_FILES, AGENT_FILES(去掉它本地的 _BRAIN/_AGENTS;_SKILLS 留在 server.py,doctor 不查 skills)。
- def report(checks)->dict: {"ok": all(c.ok for c in checks), "checks": [asdict(c) for c in checks]}。

2) CLI 接入(loom/cli.py)
- 在 status 命令后(cli.py:154 之后)新增 @app.command(help="启动自检:检查 key/后端/agent/外置大脑。") def doctor():
  - root=find_project_root()(捕获 FileNotFoundError→_die);from .doctor import run_checks;checks=run_checks(root)。
  - 用 rich Table 渲染:每行 名目 + ✓/✗ + 缺什么 + 怎么补;全过打印绿色"全部就绪"。
  - 末尾 raise typer.Exit(0 if all ok else 1)(对齐 WW 退出码语义,便于脚本/打包自检)。

3) server 接入(loom/server.py)
- 顶部 import: from .doctor import run_checks, report, BRAIN_FILES, AGENT_FILES。
- 在 project_state 路由后(server.py:97 之后)新增:
  @app.get("/api/doctor")
  def doctor(root: str):
      return report(run_checks(Path(root)))
- 只读、无副作用,符合本地单用户无鉴权约定(server.py:1-4)。

4) WebUI 接入(loom/webui/index.html + app.js)
- index.html:在 topbar 的"切换项目"按钮旁(index.html:50 附近)加 <button id="btn-doctor" class="ghost">自检</button>。
- app.js:bind() 里(app.js:43 前)加 $("btn-doctor").onclick = runDoctor;新增 async function runDoctor(){ const d = await jreq("GET", `/api/doctor?root=${encodeURIComponent(DATA.root)}`); 把非 ok 的 checks 逐条 toast 或在 run 日志区列出"缺什么→怎么补",全过则 toast("环境就绪") }。复用现有 jreq(app.js:8-15)和 toast(app.js:16-21),不新增 UI 框架。

## 代码草图

# loom/doctor.py  (新增,无新依赖)
from __future__ import annotations
import importlib.util, shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from .config import load_config, key_is_set

BRAIN_FILES = ["世界观", "人物卡", "卡章纲", "写作指纹"]   # 外置大脑四件套(server.py 复用)
AGENT_FILES = ["设定师", "大纲师", "写手", "编辑", "润色师"]  # 5 个 agent

@dataclass
class Check:
    name: str
    ok: bool
    missing: str = ""   # 缺什么(仅 ok=False)
    fix: str = ""       # 怎么补(仅 ok=False)

def _c(name, ok, missing="", fix=""):
    return Check(name, ok, "" if ok else missing, "" if ok else fix)

def run_checks(root: Path) -> list[Check]:
    checks: list[Check] = []
    # a. loom.toml 可解析
    try:
        cfg = load_config(root)
        checks.append(_c("loom.toml 可解析", True))
    except Exception as e:
        checks.append(_c("loom.toml 可解析", False,
                         f"无法读取/解析:{e}", "确认 loom.toml 存在且为合法 TOML,或重新 loom init"))
        return checks  # 没配置,后面的检查无意义,提前返回
    prov = (cfg.provider or "deepseek").lower()
    # b. provider 凭据(仅 deepseek 需要 key)
    if prov == "deepseek":
        checks.append(_c("DEEPSEEK_API_KEY 已配", key_is_set(root),
                         ".env 里没读到 DEEPSEEK_API_KEY",
                         ".env 加一行 DEEPSEEK_API_KEY=sk-你的key(platform.deepseek.com 申请)"))
    # c. provider 对应命令/库
    if prov == "deepseek":
        checks.append(_c("openai 库已装", importlib.util.find_spec("openai") is not None,
                         "没装 openai 库", "pip install openai"))
    elif prov == "claude":
        checks.append(_c("claude 命令可用", shutil.which("claude") is not None,
                         "PATH 里没有 claude", "装 Claude Code 并确保 claude 在 PATH"))
    elif prov == "codex":
        checks.append(_c("codex 命令可用", shutil.which("codex") is not None,
                         "codex 后端 v0.1 未接", "先把 provider 改成 deepseek 或 claude"))
    else:
        checks.append(_c("provider 受支持", False,
                         f"未知 provider={prov!r}", "loom.toml 里改成 deepseek/claude/codex"))
    # d. 5 个 agent 文件齐
    for n in AGENT_FILES:
        p = root / "agents" / f"{n}.md"
        checks.append(_c(f"agent · {n}", p.is_file(),
                         f"缺 agents/{n}.md", f"补回 agents/{n}.md(可对照 loom init 模板)"))
    # e. 外置大脑四件套在
    for n in BRAIN_FILES:
        p = root / "外置大脑" / f"{n}.md"
        fix = ("loom seed 重新生成,或从备份恢复" if n == "写作指纹"
               else f"外置大脑是人维护文件,手动补回 外置大脑/{n}.md")
        checks.append(_c(f"外置大脑 · {n}", p.is_file(), f"缺 外置大脑/{n}.md", fix))
    return checks

def report(checks: list[Check]) -> dict:
    return {"ok": all(c.ok for c in checks), "checks": [asdict(c) for c in checks]}

# ---- loom/cli.py  接入点:status 命令(cli.py:131)之后新增 ----
@app.command(help="启动自检:检查 key/后端命令/agent/外置大脑齐不齐。")
def doctor() -> None:
    from .doctor import run_checks
    try:
        root = find_project_root()
    except FileNotFoundError as e:
        _die(str(e))
    checks = run_checks(root)
    if all(c.ok for c in checks):
        console.print("[bold green]✓ 环境就绪,可以开写。[/bold green]")
        raise typer.Exit(0)
    table = Table(title="启动自检 · 待修复")
    for col in ("检查项", "缺什么", "怎么补"):
        table.add_column(col)
    for c in checks:
        if not c.ok:
            table.add_row(f"[red]✗ {c.name}[/red]", c.missing, c.fix)
    console.print(table)
    raise typer.Exit(1)

# ---- loom/server.py  接入点:project_state(server.py:94-96)之后新增 ----
from .doctor import run_checks, report  # 顶部 import 区
@app.get("/api/doctor")
def doctor(root: str):
    return report(run_checks(Path(root)))

// ---- loom/webui/app.js  bind()(app.js:43 前)+ 新函数 ----
$("btn-doctor").onclick = runDoctor;
async function runDoctor() {
  try {
    const d = await jreq("GET", `/api/doctor?root=${encodeURIComponent(DATA.root)}`);
    const bad = d.checks.filter(c => !c.ok);
    if (!bad.length) { toast("环境就绪,可以开写"); return; }
    bad.forEach(c => toast(`✗ ${c.name}:${c.missing} → ${c.fix}`, true));
  } catch (e) { toast(e.message, true); }
}
<!-- loom/webui/index.html  topbar(index.html:50 附近)加按钮 -->
<button id="btn-doctor" class="ghost">自检</button>

## 验收标准

- [ ] loom/doctor.py 新增,run_checks(root) 是纯函数,内部全部 try/except 包成 Check,任何缺失/坏配置都不抛栈而是返回一条 ok=False 的 Check(缺什么 + 怎么补)
- [ ] loom.toml 不可解析时只返回一条 loom.toml Check 并提前 return(不再对坏配置做后续无意义检查)
- [ ] deepseek 缺 DEEPSEEK_API_KEY 时报出且给出 .env 修复指引;deepseek 缺 openai 库 / claude 缺 claude 命令 / codex 缺 codex 命令 各自单独成项并给修复
- [ ] 5 个 agent 文件(设定师/大纲师/写手/编辑/润色师)缺任一即报出对应行;外置大脑四件套(世界观/人物卡/卡章纲/写作指纹)缺任一即报出对应行
- [ ] `loom doctor` 全过打印绿色就绪并 exit 0;有缺时用 rich Table 列出 检查项/缺什么/怎么补 并 exit 1
- [ ] GET /api/doctor?root=... 返回 {ok, checks:[{name,ok,missing,fix}]},只读无副作用
- [ ] WebUI topbar 出现『自检』按钮,点击全过 toast 就绪、有缺时逐条 toast 缺什么→怎么补
- [ ] server.py 的 _BRAIN/_AGENTS 与 doctor.py 的 BRAIN_FILES/AGENT_FILES 不再各存一份(server 改为从 doctor 导入),清单单一真相
- [ ] doctor 只查 6 项(key、provider 命令/库、loom.toml、agent、外置大脑),不含 SQLite/RAG/projection/dashboard/phase/severity 分级

## 红线(防变味)

- ⛔ 只读自检:doctor 绝不写任何文件、不触发 seed/learn/write、不调用任何后端 LLM,纯 stat + find_spec + which,守『本地、不花钱、无副作用』
- ⛔ 守红线③极简:不引入 SQLite/向量库/projection/dashboard 校验/phase 状态机/severity 三级分级/schema_version,只有 ok|缺失 二态 + 一行修复
- ⛔ 守『像你』隔离:doctor 只检查写作指纹.md 是否存在,绝不读取/解析/校验其内容,更不碰 diff/learn 逻辑,不让自检逻辑触碰文风蒸馏
- ⛔ doctor 不检查任何剧情套路内容(题材/金手指/拆书),它只管文件在不在、命令通不通,不涉 what/voice 边界
- ⛔ 缺失项的 fix 文案对『外置大脑(人维护 file-as-truth)』与『写作指纹(seed 生成)』区分对待:人维护文件提示手动补回,绝不建议用 AI 自动重建外置大脑
- ⛔ doctor 失败不阻断任何现有命令:它是独立诊断,不在 write/seed 路径里加前置门禁(避免把极简工具变成强校验中间件)

