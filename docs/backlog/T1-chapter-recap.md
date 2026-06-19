# T1-chapter-recap · 写后摘要补卡章纲(命门):learn 接受一章后从手改终稿抽摘要+伏笔行 write-once 回填卡章纲
- **类型**: code　**工作量**: medium　**批次**: 批次2 · 命门与续跑(改 agents/fingerprint 主流程,需谨慎)
- **依赖**: 无
- **涉及文件**:
  - `loom/recap.py`
  - `loom/fingerprint.py`
  - `loom/templates/外置大脑/卡章纲.md`
  - `loom/server.py`
  - `loom/webui/app.js`

## 问题(Loom 现状)

Loom 当前跨章记忆只有两根支柱:卡章纲(人维护的一句话脊柱)+ 上一章手改正文。卡章纲是【写前规划】,写完后没有任何机制把"这章实际写成了什么、埋/推/收了哪些伏笔"沉淀回去。写到第 30 章时,大纲师只能看到当初规划的一句话 + 紧邻的上一章全文,中间几十章的伏笔状态全靠作者脑子记。这是 v0.2 命门:剧情连续性会断。

现状证据:
- loom/agents.py:92-97 _prev_chapter() 只回读"上一章"正文,没有跨更早章节的压缩记忆。
- loom/templates/agents/大纲师.md reads 只有 外置大脑/卡章纲.md + skills/故事引擎.md;卡章纲每章只有规划行(卡章纲.md:7-9 形如「- 第N章:…」),没有"写后回顾"。
- loom/fingerprint.py:112-139 learn() 接受一章后只更新写作指纹、mark_learned,没有任何回填脊柱的动作。learn 是作者"认领这一章为定稿"的唯一自然时机 —— 写后摘要应当挂在这里,零新增触发动作。

要做的事:learn 成功后,从【手改终稿】(正文/第N章.md,不是 .原稿 快照)抽 ≤150 字摘要 + 本章新增/推进/回收的伏笔行,write-once 追加进卡章纲第 N 章对应行下方的「AI 回顾」子块。下游大纲师已经 reads 卡章纲,零新管道。

## 从 webnovel-writer 借什么 / 丢什么

借鉴源已读:
- /tmp/webnovel-writer/webnovel-writer/agents/data-agent.md §3D「摘要与场景切片」:摘要 100-150 字;伏笔范式「## 伏笔 / - [埋设] 三年之约提及」「埋设→open_loop_created、回收→promise_paid_off」。只取这一个思想:写后从正文抽【≤150字摘要 + 伏笔行(埋设/推进/回收三态)】回写脊柱。
- /tmp/webnovel-writer/webnovel-writer/scripts/extract_chapter_context.py 的 _load_summary_file / extract_chapter_summary:用正则 `##\s*剧情摘要\s*\n(.+?)(?=\n##|$)` 从 markdown 切摘要段;以及"摘要落地为  chNNNN.md、按章号定位"的思路 —— 只借"摘要是一段可被正则切出的 markdown、按章号定位"这个轻量形态。

明确丢弃(违红线③或过重):
- CHAPTER_COMMIT / 投影链(projection)/ 状态机 / SubagentRun 汇总信号(data-agent §7/§9 整套 artifact schema)。
- SQLite / state.json 的 strand_tracker / plot_threads.foreshadowing 结构化伏笔库、urgency 打分(extract_chapter_context.py:extract_state_summary)—— 不引入打分引擎。
- RAG / 向量检索触发词(extract_chapter_context.py:_RAG_TRIGGER_KEYWORDS / _build_rag_query / _search_with_rag)整段丢弃。
- entity 索引 / 别名消歧 / 三份 JSON artifact / event_id 枚举 —— 全丢,Loom 不做实体库。
- 不复用它的 .webnovel/summaries/chNNNN.md 独立文件树:Loom 坚持 file-as-truth 单文件,摘要直接进卡章纲,不另起一套摘要目录。

## Loom 落地设计

新建 loom/recap.py(与 fingerprint.py 并列、同形:纯引擎、progress 回调、不依赖前端),不污染 fingerprint.py 的指纹逻辑(物理隔离,守红线②)。

接入点 1 — loom/recap.py 新文件,核心函数:
- recap_chapter(project_root: Path, chapter_n: int, backend: Backend, progress=_noop) -> Path | None
- 读 正文/第N章.md(手改终稿);调 backend.complete(_RECAP_SYSTEM, user, max_chars≈600) 抽「摘要(≤150字)+ 伏笔行(- [埋设/推进/回收] …)」;调 _append_recap() write-once 写回卡章纲。

接入点 2 — loom/fingerprint.py:137,learn() 内 mark_learned(project_root, chapter_n) 之后、return 之前,挂钩调用 recap_chapter(...)。包在 try/except LoomBackendError 里:recap 失败不能让 learn 失败(指纹已经写好了,摘要是附赠)。或更干净:不改 fingerprint.py,改在 server.py:170 fp_learn(...) 成功后再调一次 recap(见接入点 4 备选)。推荐挂在 learn() 内,保证 CLI 与 server 两条路都生效。

接入点 3 — loom/recap.py:_append_recap(),write-once 语义(守红线①②):
- 在卡章纲.md 里按行匹配 `^- 第{chapter_n}章[:：]`(兼容中英文冒号)定位该章规划行。
- 若该规划行下方已存在本章「  - [AI回顾]」缩进子块 → 不覆盖、直接 return None(write-once,人重 learn 同一章不重复追加)。
- 若不存在 → 在该规划行后插入缩进子块。绝不修改作者手写的规划行本身。
- 子块物理标记 [AI回顾],与人写内容视觉隔离,可手改可删,绝不回流写作指纹(红线②)。

接入点 4 — loom/server.py:166-173 /api/learn:learn() 内部已挂 recap,返回体可加 `"卡章纲": (root/"外置大脑"/"卡章纲.md").read_text(...)` 供前端刷新预览。若想要独立 /api/recap(用户单独补摘要不重学指纹),再加一个薄端点调 recap_chapter —— v0.2 可省。

接入点 5 — loom/webui/app.js:157-164 learn(n):learn 成功后已 refresh + 打开写作指纹;追加一句 toast「已把第N章写后摘要补进卡章纲」并可顺带 openFile("外置大脑/卡章纲.md") 让作者一眼看到回填结果。

接入点 6 — loom/templates/外置大脑/卡章纲.md:顶部说明补一句解释「- [AI回顾]」子块是写后自动补的、可手改可删,不影响大纲师读规划行。大纲师.md 的 reads 无需改(已含卡章纲)。

数据流:正文/第N章.md(手改终稿,真源)→ recap_chapter 抽摘要+伏笔 → write-once 进 外置大脑/卡章纲.md 的 [AI回顾] 子块 → 下一章 run_pipeline 时大纲师 _read_files 读到整份卡章纲(含回顾)→ 衔接前情。摘要绝不进 .原稿 快照、绝不进写作指纹。

## 代码草图

### loom/recap.py(新建)

```python
"""写后摘要:learn 接受一章后,从【手改终稿】抽 ≤150 字摘要 + 伏笔行,
write-once 回填卡章纲对应章行下的「AI回顾」子块。

红线:
- 只读手改终稿(正文/第N章.md),不是 .原稿 快照。
- 摘要/伏笔只管 what(剧情脊柱),进卡章纲,绝不喂写作指纹(红线①)。
- write-once:同章重复 learn 不覆盖、不重复追加(红线②,人写优先)。
- 不引入实体库/打分/向量(红线③)。
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Callable
from .backends import Backend, LoomBackendError

Progress = Callable[[dict], None]
def _noop(e: dict) -> None: ...

CARD_REL = "外置大脑/卡章纲.md"
_RECAP_MARK = "[AI回顾]"   # 物理隔离标记

_RECAP_SYSTEM = """你是剧情脊柱记录员。我给你某一章的【作者定稿正文】。
请只描述这一章【实际写成了什么】(管 what,不管文笔好坏、不评价风格)。
严格输出下面两段,不要任何额外解释:
摘要:<一句话到三句话,≤150字,这章发生了什么、推进到哪>
伏笔:
- [埋设] <这章新埋的悬念/线索;没有就省略这行>
- [推进] <这章把某条已有线索往前推了;没有就省略>
- [回收] <这章兑现/闭合了之前的某个悬念;没有就省略>
若某类伏笔没有就不输出那一行;三类都没有则伏笔下写「- 无」。"""

def recap_chapter(project_root: Path, chapter_n: int,
                  backend: Backend, progress: Progress = _noop) -> Path | None:
    final_path = project_root / "正文" / f"第{chapter_n}章.md"
    if not final_path.exists():
        return None  # 没正文不报错(recap 是附赠,不阻断 learn)
    card_path = project_root / CARD_REL
    if not card_path.exists():
        return None

    # write-once 前置检查:该章已有 [AI回顾] 子块就直接跳过,绝不二次调用 LLM
    card = card_path.read_text(encoding="utf-8")
    if _already_recapped(card, chapter_n):
        progress({"type": "recap_skip", "chapter": chapter_n})
        return None

    final = final_path.read_text(encoding="utf-8").strip()
    progress({"type": "info", "message": f"正在为第 {chapter_n} 章补写后摘要…"})
    raw = backend.complete(_RECAP_SYSTEM, f"第 {chapter_n} 章定稿正文:\n\n{final}", max_chars=600)
    block = _format_block(chapter_n, raw)

    new_card = _append_recap(card, chapter_n, block)
    if new_card is None:           # 没找到该章规划行 / 已存在
        progress({"type": "recap_skip", "chapter": chapter_n})
        return None
    card_path.write_text(new_card, encoding="utf-8")
    progress({"type": "recap_done", "chapter": chapter_n, "path": str(card_path)})
    return card_path

_CH_LINE = lambda n: re.compile(rf"^- 第{n}章[:：]")

def _already_recapped(card: str, n: int) -> bool:
    lines = card.splitlines()
    for i, ln in enumerate(lines):
        if _CH_LINE(n).match(ln):
            # 看紧随其后的缩进子块里有没有 [AI回顾]
            for nxt in lines[i+1:]:
                if nxt and not nxt.startswith((" ", "\t")):  # 到下一条顶格章行就停
                    break
                if _RECAP_MARK in nxt:
                    return True
            return False
    return False

def _format_block(n: int, raw: str) -> str:
    # 把 LLM 两段输出折成卡章纲下的缩进子块;截断摘要 ≤150 字硬保险
    text = raw.strip()
    m = re.search(r"摘要[:：]\s*(.+?)(?=\n伏笔|$)", text, re.DOTALL)
    summary = (m.group(1).strip() if m else text)[:150]
    fm = re.search(r"伏笔[:：]?\s*\n(.+)$", text, re.DOTALL)
    fore = fm.group(1).strip() if fm else "- 无"
    foreshadow = "\n".join("    " + l.strip() for l in fore.splitlines() if l.strip())
    return (f"  - {_RECAP_MARK} 摘要:{summary}\n"
            f"    伏笔:\n{foreshadow}")

def _append_recap(card: str, n: int, block: str) -> str | None:
    lines = card.splitlines()
    for i, ln in enumerate(lines):
        if _CH_LINE(n).match(ln):
            # 跳过该章已有的缩进子块,插在其末尾(不动作者手写的规划行)
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                if _RECAP_MARK in lines[j]:
                    return None   # write-once:已存在
                j += 1
            lines.insert(j, block)
            return "\n".join(lines) + ("\n" if card.endswith("\n") else "")
    return None  # 卡章纲里没有这章的规划行
```

### loom/fingerprint.py 接入(learn() 内,行 137 之后)

```python
    mark_learned(project_root, chapter_n)
    # 写后摘要补卡章纲:附赠动作,失败不阻断 learn(指纹已落盘)
    try:
        from .recap import recap_chapter
        recap_chapter(project_root, chapter_n, backend, progress)
    except LoomBackendError as e:
        progress({"type": "warn", "message": f"写后摘要没补成(不影响指纹):{e}"})
    progress({"type": "learn_done", "path": str(fp_path), "chapter": chapter_n})
    return fp_path
```

### loom/server.py /api/learn 返回体(行 173)可选增补
```python
    return {"ok": True,
            "fingerprint": (root/"外置大脑"/"写作指纹.md").read_text(encoding="utf-8"),
            "卡章纲": (root/"外置大脑"/"卡章纲.md").read_text(encoding="utf-8")}
```

### loom/webui/app.js learn() (行 159 后)
```javascript
    await jreq("POST", "/api/learn", { root: DATA.root, chapter: n });
    toast(`已把第${n}章的手改学进指纹,并把写后摘要补进卡章纲`);
    await refresh();
    openFile("外置大脑/卡章纲.md", true, null);  // 让作者一眼看到回填的 [AI回顾]
```

## 验收标准

- [ ] learn 第 N 章成功后,外置大脑/卡章纲.md 里第 N 章规划行下方出现一个缩进的「- [AI回顾] 摘要:…」子块,摘要 ≤150 字。
- [ ] 该子块含「伏笔:」段,按 [埋设]/[推进]/[回收] 三态列出本章伏笔;三态都无时显示「- 无」。
- [ ] write-once 验证:对同一章再次 learn,卡章纲不出现第二个 [AI回顾] 子块,且不重复调用 LLM(recap_skip 事件)。
- [ ] 作者手写的「- 第N章:…」规划行内容在 recap 前后逐字不变;[AI回顾] 子块作为缩进子项物理隔离、可手改可删。
- [ ] recap 只读 正文/第N章.md(手改终稿),不读 .原稿 快照;摘要/伏笔内容不出现在 写作指纹.md 里(grep 验证无回流)。
- [ ] 卡章纲里没有第 N 章规划行时,recap 安全跳过(返回 None),learn 仍正常完成。
- [ ] backend.complete 抛 LoomBackendError 时 learn 不失败:指纹已落盘,只发 warn,return fp_path 正常。
- [ ] 下一章跑 run_pipeline 时大纲师读到的卡章纲含 [AI回顾] 子块(_read_files 整文件读入,无需改 reads)。

## 红线(防变味)

- ⛔ 像你:摘要/伏笔只描述剧情 what(这章发生了什么、埋/推/收什么),_RECAP_SYSTEM 显式禁止评价文笔/风格;产物只进卡章纲(设定师/大纲师域),绝不进写作指纹或喂写手(红线①)。
- ⛔ 物理隔离:AI 生成的回顾带 [AI回顾] 标记、缩进子块,与人写规划行视觉+结构隔离,可手改可删,绝不回流写作指纹(红线②)。
- ⛔ 极简:新建 recap.py 一个文件 + learn 内一处挂钩 + 卡章纲一段说明;不动 agents.py 主流程、不加新 reads、不新增前端按钮(复用 learn 触发)。
- ⛔ 本地/反过度工程:不引入 SQLite/向量库/投影链/打分(urgency)/状态机;摘要直接 file-as-truth 进卡章纲,不另起摘要目录树(红线③)。
- ⛔ write-once:同章重复 learn 不覆盖人可能已手改的回顾、不重复追加;人写内容永远优先。
- ⛔ recap 失败必须降级:learn 的本职(学指纹)已完成就不能因 recap 报错而回滚或抛错。

