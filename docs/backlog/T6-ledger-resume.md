# T6-ledger-resume · 极简 ledger 断点续跑:记 sha + 跳过未变工序,省 DeepSeek 重算
- **类型**: code　**工作量**: medium　**批次**: 批次2 · 命门与续跑(改 agents/fingerprint 主流程,需谨慎)
- **依赖**: 无
- **涉及文件**:
  - `loom/ledger.py`
  - `loom/agents.py`
  - `loom/cli.py`
  - `loom/server.py`

## 问题(Loom 现状)

Loom 的 run_pipeline(loom/agents.py:100-150)把 5 个 agent 的产物只攒在内存 list `workspace` 里,跑到底才在 _save_chapter(agents.py:153)落 正文/第N章.md。中途断网/DeepSeek 报错(server.py:201 的 except)会把整章前功尽弃,下次 write 必从设定师重头跑 5 次 LLM 调用——DeepSeek 按字计费,这是纯浪费钱。

现状缺失:
① 没有任何"这一章的哪几道工序已完成、产物是什么"的落盘记录,工序产物随进程消失,无法续跑。
② 已有的"手改过拒覆盖"判断散在 cli.py:107-111 和 server.py:188-192,只比对 正文/第N章.md vs 正文/.原稿/第N章.md 的 strip 后文本,逻辑重复、且只能挡覆盖,既不能跳过已完成工序,也不能在"手改过但你确实想续跑"时给确认而非硬拒。
③ 没有上游工序变更检测:即便记了 ledger,若用户改了 卡章纲/世界观,旧的设定师产物本该作废重跑,当前无机制感知。

要做的:把 WW 的 file_signature + resume_from 思想砍到最薄一层接进来。正文/.原稿/第N章.ledger.json 记每道工序的 sha256 + 产物文本 + 上游签名;resume 时跳过"已完成且上游未变"的工序;只在 正文/第N章.md 的 sha 与快照不符时要求确认。

## 从 webnovel-writer 借什么 / 丢什么

借鉴源:/tmp/webnovel-writer/webnovel-writer/scripts/data_modules/run_ledger.py(WW 唯一真正的 ledger 实现,407 行)。

【借这几个精华函数的"形",重写不照搬】
- file_signature(path) (run_ledger.py:71-83):返回 sha256(read_bytes)+size+mtime_ns+exists 的 dict。Loom 只取 sha256+exists 两字段即够(mtime/size 是 WW 的快路径优化,极简原则下丢弃,sha 直读不慢)。
- record_write_step(..., status, inputs, outputs) (run_ledger.py:101-139):把每步的输入/输出签名+状态写进 ledger 并 save。Loom 简化成"记某工序的 produces 文本 + 上游签名"。
- _same_signature(expected, current) (run_ledger.py:142-145):exists 且 sha256 相等才算未变——这是"跳过判定"的内核,直接照抄语义。
- build_write_resume_plan 里 resume_from 的求法(run_ledger.py:300-304):按顺序找第一个非 skip 的工序作为续跑起点——这个三行循环是整个 resume 的灵魂,照抄。
- 正文 sha 与快照不符 → needs_user_confirmation 的 code+message 思路(run_ledger.py:236-243 的 chapter_file_changed):Loom 复用这一条确认语义,合并掉自己已有的"手改过拒覆盖"。

【明确丢弃(WW 重基础设施/CC 依赖/多步状态机,触 Loom 红线③)】
- SCHEMA_VERSION 迁移协商 + sort_keys JSON 规整(run_ledger.py:33,55-61,67):过度工程。Loom ledger 只服务单章续跑,读坏就当无 ledger 重跑即可,无需 schema 版本协商。
- 整套 commit/projection/backup/data/review 多步状态机(run_ledger.py:176-298):trusted/accepted/rejected、_commit_status、_projection_done、_backup_exists、_latest_contract_mtime、REQUIRED_PROJECTION_WRITERS——全是 WW 的"故事事实提交+资料投影"重链路,Loom 没有也绝不要(红线③不引入打分/投影链)。
- artifact_validator / project_phase / projection_log / chapter_paths 的全部 import(run_ledger.py:18-30):CC 插件解析层依赖,Loom 自己有路径约定(正文/第N章.md),不引入。
- argparse CLI main()(run_ledger.py:357-406):Loom 走 typer cli.py / FastAPI server.py,不要独立 CLI 入口。
- mode/duration_ms/problems/auto_handled 等字段:Loom 工序无这些维度,砍掉。

## Loom 落地设计

【新建 loom/ledger.py(~70 行,纯函数 + file-as-truth,不碰写作指纹)】

数据形态——正文/.原稿/第N章.ledger.json:
{
  "chapter": 7,
  "snapshot_sha": "<上次落盘时 正文/第7章.md 的 sha>",
  "steps": {
    "设定师": {"output_sha": "<produces文本sha>", "output": "<produces全文>", "upstream_sha": "<入此工序时的上游签名sha>"},
    "大纲师": {...}
  }
}
- output 存全文是为了续跑时把已完成工序的产物重新塞回 workspace(否则跳过后下游拿不到上游产物)。这是 Loom 与 WW 的关键差异:WW 产物在磁盘文件里,Loom 工序产物是内存文本,必须随 ledger 落盘。

函数签名(全部纯函数,project_root + chapter 显式传入):
- _ledger_path(root, n) -> Path  → root/"正文"/".原稿"/f"第{n}章.ledger.json"
- sha(text: str) -> str  → hashlib.sha256(text.encode()).hexdigest()
- load_ledger(root, n) -> dict  → 读不到/坏 JSON 返回 {"chapter": n, "snapshot_sha": "", "steps": {}}(照 WW load_ledger 的容错,run_ledger.py:46-51)
- save_ledger(root, n, led) -> None  → mkdir parents + ensure_ascii=False indent=2
- record_step(root, n, role, output, upstream_sha) -> None  → 写一道工序进 steps 并 save_ledger
- record_snapshot(root, n, final_text) -> None  → 落盘正文后写 snapshot_sha
- upstream_sha(root, role, workspace, prev) -> str  → 把该 role 的 reads 文件内容 + 已累积 workspace 文本 + prev 拼起来取 sha,作为"上游签名"
- resume_point(root, n, agents_reads) -> tuple[int, list]:返回 (起始工序下标, 预填 workspace)。逐 role 比对 ledger.steps[role] 是否存在且 upstream_sha 与当前一致(_same_signature 语义);第一个不匹配的工序即起点,其前的产物预填进 workspace。照抄 run_ledger.py:300-304 找 resume_from 的循环。
- chapter_drifted(root, n) -> bool:正文/第N章.md 存在且 sha != ledger.snapshot_sha → True(对应 WW chapter_file_changed,run_ledger.py:236)

【改 loom/agents.py:run_pipeline(100-150)接入点】
- 110 行 progress(pipeline_start) 之后,新增参数 `resume: bool = True`。若 resume:调 ledger.resume_point() 得到 (start_idx, prefill_workspace),用 prefill_workspace 初始化 workspace,for 循环 `for role in PIPELINE[start_idx:]`。对 start_idx 之前的 role 发 progress({"type":"agent_skip","role":role,"reason":"已完成且上游未变"})。
- 循环体内 134 行 backend.complete 拿到 output 后、append workspace 前,插一行:计算 upstream_sha 并 ledger.record_step(project_root, chapter_n, role, output, up_sha)。每道工序产物即时落盘——这是省钱的关键,断在第3步时前2步已持久化。
- 141 行 _save_chapter 之后,调 ledger.record_snapshot(project_root, chapter_n, final),把终稿 sha 写进 ledger。
- backend.complete 的异常不在此 try(由 server.py:201 / cli.py:115 兜),但因为 record_step 即时落盘,异常时 ledger 已有完成工序,天然支持续跑。

【改 loom/cli.py:write(99-116)合并 drift 逻辑】
- 删除 107-111 行现有的 out/snap strip 比对块。
- 改为:若 out.exists() 且 not force → 调 ledger.chapter_drifted(root, chapter);drifted 则 _die("第 N 章正文与上次记录不符(你手改过?)。先 learn N,或加 --force 续跑会以你的正文为准。");未 drift 但 ledger 显示全部工序完成 → _die("第 N 章已写完。要重写加 --force。")。
- run_pipeline 调用传 resume=not force(force 时全重跑,不 force 时续跑)。

【改 loom/server.py:write(183-217)同步 drift 逻辑】
- 删除 188-192 现有 out/snap 比对块,改用 ledger.chapter_drifted,返回 409 + {"error": ..., "code": "chapter_drifted"}(给前端区分"手改冲突"与"已存在")。
- worker() 内 run_pipeline 传 resume=not b.force。

数据流:write → resume_point 读 ledger 决定从哪步起 → 逐步 backend.complete 并 record_step 落盘 → 终稿落盘 record_snapshot。断网重来 → resume_point 跳过已落盘且上游未变的工序 → 只重算剩余工序。

## 代码草图

# ===== loom/ledger.py(新建)=====
from __future__ import annotations
import hashlib, json
from pathlib import Path

def _ledger_path(root: Path, n: int) -> Path:
    return root / "正文" / ".原稿" / f"第{n}章.ledger.json"

def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def load_ledger(root: Path, n: int) -> dict:
    p = _ledger_path(root, n)
    if not p.exists():
        return {"chapter": n, "snapshot_sha": "", "steps": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"chapter": n, "snapshot_sha": "", "steps": {}}
    except Exception:               # 坏 JSON → 当无 ledger,重跑(极简:不做 schema 协商)
        return {"chapter": n, "snapshot_sha": "", "steps": {}}

def save_ledger(root: Path, n: int, led: dict) -> None:
    p = _ledger_path(root, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")

def record_step(root: Path, n: int, role: str, output: str, upstream_sha: str) -> None:
    led = load_ledger(root, n)
    led["steps"][role] = {"output_sha": sha(output), "output": output, "upstream_sha": upstream_sha}
    save_ledger(root, n, led)

def record_snapshot(root: Path, n: int, final_text: str) -> None:
    led = load_ledger(root, n)
    led["snapshot_sha"] = sha(final_text.strip())
    save_ledger(root, n, led)

def chapter_drifted(root: Path, n: int) -> bool:
    out = root / "正文" / f"第{n}章.md"
    if not out.exists():
        return False
    led = load_ledger(root, n)
    if not led.get("snapshot_sha"):
        return False
    return sha(out.read_text(encoding="utf-8").strip()) != led["snapshot_sha"]

def resume_point(root: Path, n: int, upstream_of):
    """upstream_of(role, workspace) -> 当前上游签名 sha。
    返回 (start_idx, prefill_workspace)。照 WW resume_from(run_ledger.py:300-304):
    顺序找第一个 ledger 缺失或上游签名不符的工序作起点。"""
    from .agents import PIPELINE
    led = load_ledger(root, n)
    steps = led.get("steps", {})
    workspace: list[tuple[str, str]] = []
    for i, role in enumerate(PIPELINE):
        entry = steps.get(role)
        if not entry or entry.get("upstream_sha") != upstream_of(role, workspace):
            return i, workspace            # 此工序起重跑,其前产物已预填
        workspace.append((_produces(role), entry["output"]))   # 复用 agents._PRODUCES
    return len(PIPELINE), workspace        # 全部完成

# ===== loom/agents.py:run_pipeline 接入点(改)=====
def run_pipeline(project_root, chapter_n, backend, config, progress=_noop, *, slow=0.0, resume=True):
    from . import ledger
    progress({"type": "pipeline_start", "chapter": chapter_n, "roles": PIPELINE})
    prev = _prev_chapter(project_root, chapter_n)

    def _upstream_of(role, ws):            # reads 文件 + 已累积 workspace + prev 的合并签名
        a = load_agent(project_root, role)
        rels = list(a.reads) + (a.reads_first_chapter if chapter_n == 1 else [])
        knowledge = _read_files(project_root, rels, _noop)
        ws_text = "\n".join(t for _, t in ws)
        return ledger.sha(knowledge + " " + ws_text + " " + prev)

    if resume:
        start_idx, workspace = ledger.resume_point(project_root, chapter_n, _upstream_of)
        for role in PIPELINE[:start_idx]:
            progress({"type": "agent_skip", "role": role, "reason": "已完成且上游未变"})
    else:
        start_idx, workspace = 0, []

    for role in PIPELINE[start_idx:]:
        agent = load_agent(project_root, role)
        progress({"type": "agent_start", "role": role})
        up_sha = _upstream_of(role, workspace)          # 记录入此工序时的上游签名
        # ... 原 118-133 行拼 prompt 不变 ...
        output = backend.complete(agent.system_prompt, "\n\n".join(parts), max_chars=max_chars)
        ledger.record_step(project_root, chapter_n, role, output, up_sha)   # ★ 即时落盘=省钱
        workspace.append((agent.produces, output))
        progress({"type": "agent_done", "role": role, "produces": agent.produces})
        if slow: time.sleep(slow)

    final = workspace[-1][1]
    path = _save_chapter(project_root, chapter_n, final)
    ledger.record_snapshot(project_root, chapter_n, final)                  # ★ 终稿快照
    progress({"type": "chapter_done", ...})   # 不变
    return path, final

# ===== loom/cli.py:write 接入点(改,合并 drift)=====
# 删 107-111 行旧 out/snap 比对,改为:
from . import ledger
if out.exists() and not force:
    if ledger.chapter_drifted(root, chapter):
        _die(f"第 {chapter} 章正文与上次记录不符(你手改过?)。先 learn {chapter},或加 --force 以你的正文为准续跑。")
    if ledger.all_done(root, chapter):     # 可选小工具:steps 覆盖完 PIPELINE
        _die(f"第 {chapter} 章已写完。要重写加 --force。")
run_pipeline(root, chapter, get_backend(config), config, _render, slow=0.3, resume=not force)

# ===== loom/server.py:write 接入点(改)=====
# 删 188-192 旧比对,改为:
from . import ledger
if out.exists() and not b.force and ledger.chapter_drifted(root, b.chapter):
    return JSONResponse({"error": f"第 {b.chapter} 章正文与上次记录不符(手改过?)。先 learn,或勾选覆盖续跑。",
                         "code": "chapter_drifted"}, status_code=409)
# worker(): run_pipeline(root, b.chapter, backend, cfg, q.put, slow=0.25, resume=not b.force)

## 验收标准

- [ ] 跑第 N 章时若在写手工序后(第3步)模拟 backend 抛异常,正文/.原稿/第N章.ledger.json 已含 设定师/大纲师/写手 三道工序的 output_sha + output + upstream_sha
- [ ] 重跑同一章(不加 --force)时,设定师/大纲师/写手发出 agent_skip 进度事件,backend.complete 只被调用 2 次(编辑、润色师),DeepSeek 字数计费相应减少
- [ ] 手动修改 卡章纲.md 后重跑:resume_point 检测到设定师上游签名变化,从设定师起全部重跑(start_idx=0),不发任何 agent_skip
- [ ] 手改 正文/第N章.md 后不加 --force 跑 write:cli 报『正文与上次记录不符』并退出,server 返回 409 + code=chapter_drifted,均不触发任何 LLM 调用
- [ ] 加 --force 时 resume=False,从设定师全量重跑,ledger 被全部覆盖刷新,正文以新生成为准
- [ ] 正文/.原稿/第N章.ledger.json 损坏(写入半个 JSON)时,load_ledger 返回空 ledger,write 退化为从头全量跑,不抛异常
- [ ] 写作指纹.md、外置大脑/* 在本工单全程零写入(grep 确认 ledger.py 与改动处无任何指纹/外置大脑写路径)
- [ ] ledger.py 不 import 任何向量库/sqlite/WW 的 artifact_validator/projection 模块;全文件仅依赖 hashlib/json/pathlib + loom 自身
- [ ] 正文/第N章.md 正常落盘后,record_snapshot 写入的 snapshot_sha == sha(终稿 strip 后),chapter_drifted 返回 False

## 红线(防变味)

- ⛔ ledger 只记工序产物的 sha + 文本 + 上游签名,绝不含任何剧情套路/题材/金手指语义;它是工程续跑账本,与『管 what 的设定师』和『管 voice 的写作指纹』都正交,不喂任何 agent 当知识(红线①)
- ⛔ ledger 的 output 文本是 AI 工序产物,只用于续跑时回填 workspace,物理上落在 正文/.原稿/ 下,绝不回流写作指纹.md,与 learn 的 diff 蒸馏链完全隔离(红线②)
- ⛔ 不引入 SQLite/向量库/schema 版本协商/打分引擎/投影链;ledger 是单个 plain JSON 文件,坏了就当无 ledger 重跑,刻意极简(红线③)
- ⛔ drift 检测复用并合并已有『手改过拒覆盖』逻辑,不新造第二套语义;cli/server 两处行为一致,正文永远是 file-as-truth,手改优先于 AI 快照
- ⛔ 纯本地:ledger 读写不触网、不调任何外部服务;sha 用标准库 hashlib,无新增第三方依赖

