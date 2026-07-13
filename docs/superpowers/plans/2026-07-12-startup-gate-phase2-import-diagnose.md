# 起书门禁二期 · 导入已写小说 + 整书诊断回补 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 已写好的小说能导入(正文吞进来)→ 伙伴面板「从正文提炼设定」跑一次 LLM 整书诊断,把已有主角/世界观提炼成候选让作者确认预填 → 真缺的回领航员补齐 → 同一条门禁线解锁。

**Architecture:** importer 扩「正文」桶(机械、零 LLM);新增 `diagnose.py`(读采样章 → cheap LLM 出三段候选、带正文出处、不落盘 → 作者一屏确认 → 复用既有落盘器写外置大脑,跳过 _digest);候选落盘后 journey 签名失配、领航员只问真缺、门禁自动开(零额外机制)。立项段永不进诊断(0011 不回写保留)。

**Tech Stack:** 纯 stdlib + 既有 loom 模块(importer/journey land/draft._write_sections_into_dir/parse.split_brain_draft/backends.cheap_backend/guard/continuity 证据模式)+ vanilla JS。零新依赖。

## Global Constraints(每个任务隐含遵守)

- **importer 零 LLM 红线不动**:导入纯机械(路由+搬运+重命名);诊断是导入**之后**、伙伴面板里的独立动作,不是导入的一步。
- **诊断候选确认前绝不落盘**:scan 只 return 候选(无第二真相,重启丢了重扫);commit 才落。落盘复用既有**人写优先**通道(`_write_sections_into_dir` 只写空白/模板文件、撞人写成品进 `访谈补充.md` 兜底,绝不覆盖)。
- **立项段永不进诊断**(正文无平台/对标意图,提炼必编造);ADR 0011「不回写」对诊断继续成立。
- **主角硬判对齐一期口径**:候选人物卡确认为主角 → 落 `主角·名字.md`(`_NAME_SEP=("·","・","•")`、非未命名/占位);否则导入书主角卡永锁。
- **诊断走 cheap_model**:`cheap_backend(cfg) or get_backend(cfg)`(评估/管 what,不沾指纹/voice)。
- **正文章号规范=阿拉伯**:文件名 `第N章.md`(`chapter_numbers` 用 `int(stem[1:-1])`,非阿拉伯即崩)——导入正文强制归一 `第N章.md`。
- **导入正文不造快照/ledger**(=非 Loom 织,门禁照拦——正是二期强制力所在;审核实证:无快照→chapter_drifted 恒 False、learn 已有友好拒绝,不会处处报警)。
- **`.txt` 只对正文桶放行**;设定桶维持 md-only。
- 落盘一律 `atomic_write_text`;测试统一 `.venv/bin/python -m pytest`;前端过 `node --check`;提交中文 `feat(import)/feat(diagnose)/…`。
- **拆章三叉不背**:v1 只做「一文件一章」;单大 txt 给降级话术;LLM 选切点永远归拆章工具(不做)。

---

### Task 1: 章号排序键工具(中文/阿拉伯/纯序号 → int,用于正文重命名排序)

**Files:**
- Create: `loom/cnnum.py`
- Test: `tests/test_cnnum.py`

**Interfaces:**
- Produces: `chapter_order_key(filename: str) -> tuple[int, str]`——从文件名抽章号(阿拉伯/中文/纯数字序号)作排序键;抽不到时 `(10**9, filename)`(排最后、按名兜底稳定)。`cn_to_int(s: str) -> int | None`(中文数字串→int,支持 一~九十九百…零)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cnnum.py
"""章号排序键:导入正文按真实章序重排,不被文件名字符串序(第1/第10/第2)坑。"""
from loom.cnnum import cn_to_int, chapter_order_key


def test_cn_to_int_basic():
    assert cn_to_int("一") == 1
    assert cn_to_int("十") == 10
    assert cn_to_int("十一") == 11
    assert cn_to_int("二十") == 20
    assert cn_to_int("三十五") == 35
    assert cn_to_int("一百") == 100
    assert cn_to_int("一百零一") == 101
    assert cn_to_int("两百") == 200
    assert cn_to_int("零") == 0
    assert cn_to_int("不是数字") is None


def test_chapter_order_key_arabic_sorts_numerically():
    files = ["第10章.md", "第2章.md", "第1章.md"]
    assert sorted(files, key=chapter_order_key) == ["第1章.md", "第2章.md", "第10章.md"]


def test_chapter_order_key_chinese():
    files = ["第十章.txt", "第二章.txt", "第一章.txt"]
    assert sorted(files, key=chapter_order_key) == ["第一章.txt", "第二章.txt", "第十章.txt"]


def test_chapter_order_key_pure_serial():
    files = ["10.txt", "2.txt", "1.txt"]
    assert sorted(files, key=chapter_order_key) == ["1.txt", "2.txt", "10.txt"]


def test_chapter_order_key_unparsable_last_stable():
    files = ["随便.md", "第1章.md", "楔子.md"]
    out = sorted(files, key=chapter_order_key)
    assert out[0] == "第1章.md"                    # 有章号的排前
    assert out[1:] == ["楔子.md", "随便.md"]         # 抽不到的按名稳定兜底
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_cnnum.py -v`
Expected: FAIL,`ModuleNotFoundError: loom.cnnum`

- [ ] **Step 3: 写实现**

```python
# loom/cnnum.py
"""中文/阿拉伯章号 → int 排序键。只给导入正文按真实章序重排用;纯 stdlib、不 import 任何 loom 模块。"""

from __future__ import annotations

import re

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}
_CN_CHARS = set(_CN_DIGIT) | set(_CN_UNIT)
_NUM_IN_NAME = re.compile(r"第\s*([0-9]+|[零〇一二两三四五六七八九十百千]+)\s*章")
_SERIAL = re.compile(r"^0*([0-9]+)\b")


def cn_to_int(s: str) -> int | None:
    """中文数字串 → int(一/十一/二十/三十五/一百零一/两百/零);非中文数字返回 None。"""
    s = (s or "").strip()
    if not s or any(c not in _CN_CHARS for c in s):
        return None
    return _cn_parse(s)


def _cn_parse(s: str) -> int | None:
    """确定性:遇单位(十/百/千)把暂存数字乘单位入总;「十X」开头补 1。"""
    total, cur = 0, 0
    for i, c in enumerate(s):
        if c in _CN_DIGIT:
            cur = _CN_DIGIT[c]
        elif c in _CN_UNIT:
            unit = _CN_UNIT[c]
            total += (cur if cur else 1) * unit   # 「十一」的十=1*10;「二十」的十=2*10
            cur = 0
        else:
            return None
    return total + cur


def chapter_order_key(filename: str) -> tuple[int, str]:
    """从文件名抽章号作排序键;抽不到 → (10**9, filename) 排最后、按名稳定。"""
    stem = filename.rsplit(".", 1)[0]
    m = _NUM_IN_NAME.search(stem)
    if m:
        tok = m.group(1)
        n = int(tok) if tok.isdigit() else cn_to_int(tok)
        if n is not None:
            return (n, filename)
    ms = _SERIAL.match(stem)   # 纯序号文件名 01.txt / 2.txt
    if ms:
        return (int(ms.group(1)), filename)
    return (10 ** 9, filename)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_cnnum.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add loom/cnnum.py tests/test_cnnum.py
git commit -m "feat(import): 章号排序键工具——中文/阿拉伯/纯序号→int,给导入正文按真实章序重排"
```

---

### Task 2: importer 正文桶路由 + `.txt` 收录(route + scan 端点)

**Files:**
- Modify: `loom/importer.py`(BUCKETS 14、_RULES 17、route_files 27)
- Modify: `loom/server.py`(import_scan 端点 164,rglob 收 .txt)
- Test: `tests/test_importer.py`(追加)

**Interfaces:**
- Consumes: 无(Task1 的 cnnum 在 Task3 用)
- Produces: `route_files` 识别正文(stem 命中 `第<数字>章` 或纯序号 → 正文;.txt 只进正文);`BUCKETS` 加 `"正文"`

- [ ] **Step 1: 写失败测试(追加 test_importer.py)**

```python
def test_route_chapter_files_to_body():
    from loom import importer
    routed = importer.route_files(["第1章.md", "第二章.txt", "05.txt", "世界观设定.md", "乱七八糟.md"])
    assert set(routed["正文"]) == {"第1章.md", "第二章.txt", "05.txt"}   # 章号/纯序号→正文
    assert routed["世界观"] == ["世界观设定.md"]                         # 关键词桶不变
    assert "乱七八糟.md" in routed["unknown"]                            # 猜不中仍 unknown


def test_txt_only_routes_to_body_not_setting_buckets():
    from loom import importer
    routed = importer.route_files(["人物小传.txt"])   # .txt 命中人物关键词,但 txt 只准进正文
    assert "人物小传.txt" not in routed["人物"]
    assert "人物小传.txt" in routed["unknown"]        # 非正文的 txt → unknown(设定桶 md-only)


def test_buckets_includes_body():
    from loom import importer
    assert "正文" in importer.BUCKETS
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_importer.py -k "body or txt or buckets_includes" -v`
Expected: FAIL(现无正文桶)

- [ ] **Step 3: 改 importer.py**

BUCKETS(第 14 行)加正文:

```python
BUCKETS = ("正文", "世界观", "人物", "卡章纲", "立项卡", "违禁词", "文风参考")
```

route_files(第 27-39 行)前置正文识别 + txt 限正文:

```python
_BODY_NAME = re.compile(r"^第\s*(?:[0-9]+|[零〇一二两三四五六七八九十百千]+)\s*章")
_SERIAL_NAME = re.compile(r"^0*[0-9]+$")


def route_files(names: list[str]) -> dict[str, list[str]]:
    """文件名 → 桶。正文(第N章/纯序号)前置识别;.txt 只准进正文,其余桶 md-only。"""
    out: dict[str, list[str]] = {b: [] for b in BUCKETS}
    out["unknown"] = []
    for name in names:
        stem = name.rsplit(".", 1)[0]
        ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
        if _BODY_NAME.match(stem) or _SERIAL_NAME.match(stem):
            out["正文"].append(name)
            continue
        if ext == "txt":                 # 非正文的 txt → 让作者指认(设定桶不收 txt)
            out["unknown"].append(name)
            continue
        hit = [bucket for bucket, kws in _RULES if any(kw in stem for kw in kws)]
        (out[hit[0]] if len(hit) == 1 else out["unknown"]).append(name)
    return out
```

（`_RULES` 不动;`import re` 已在文件顶部。)

- [ ] **Step 4: 改 server.py import_scan(第 164-176 行)收 .txt**

`names = sorted(...)` 那行改为同时收 md 与 txt:

```python
    names = sorted(p.name for p in folder.rglob("*") if p.suffix.lower() in (".md", ".txt") and p.is_file())
    if not names:
        return JSONResponse({"error": "这个文件夹里没有 .md 或 .txt 文件。"}, status_code=400)
```

- [ ] **Step 5: 跑测试确认通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_importer.py -v && .venv/bin/python -m pytest -q`
Expected: 全过

- [ ] **Step 6: 提交**

```bash
git add loom/importer.py loom/server.py tests/test_importer.py
git commit -m "feat(import): 正文桶路由——第N章/纯序号→正文,.txt 只准进正文;scan 端点收 .txt"
```

---

### Task 3: import_folder 正文落盘(机械重命名 第N章.md + 重排 + import_summary)

**Files:**
- Modify: `loom/importer.py`(import_folder 100、import_summary 154)
- Test: `tests/test_importer.py`(追加)

**Interfaces:**
- Consumes: `cnnum.chapter_order_key`(Task1)、`paths.chapter_path/BODY_DIR`、`_read_tolerant`、`_write_dir_file`
- Produces: import_folder 把「正文」桶的文件**按 `chapter_order_key` 排序、顺序归一为 `第1章.md 第2章.md …`** 落进 `正文/`(内容原样,txt 读容错落 md);返回值不变(root)。import_summary 补正文三句 + `original_map`(原名→章号)

- [ ] **Step 1: 写失败测试(追加 test_importer.py)**

```python
def test_import_folder_body_sequential_rename(tmp_path):
    from loom import importer, paths
    src = tmp_path / "src"; src.mkdir()
    (src / "第一章.txt").write_text("楔子内容\n", encoding="utf-8")
    (src / "第二章.txt").write_text("第二章内容\n", encoding="utf-8")
    (src / "第十章.txt").write_text("第十章内容\n", encoding="utf-8")
    routing = {b: [] for b in importer.BUCKETS}
    routing["正文"] = ["第一章.txt", "第二章.txt", "第十章.txt"]
    root = importer.import_folder(src, "导入书", routing, tmp_path / "库")
    # 按真实章序(一<二<十)顺序归一,不被字符串序坑;落成 .md
    assert paths.chapter_numbers(root) == [1, 2, 3]
    assert (root / "正文/第1章.md").read_text(encoding="utf-8").strip() == "楔子内容"
    assert (root / "正文/第3章.md").read_text(encoding="utf-8").strip() == "第十章内容"


def test_import_summary_body_notes(tmp_path):
    from loom import importer
    src = tmp_path / "src"; src.mkdir()
    (src / "第1章.txt").write_text("正文\n", encoding="utf-8")
    routing = {b: [] for b in importer.BUCKETS}; routing["正文"] = ["第1章.txt"]
    root = importer.import_folder(src, "书", routing, tmp_path / "库")
    summary = importer.import_summary(root, routing)
    assert summary["placed"]["正文"] == 1
    assert any("章" in n for n in summary["notes"])   # 有"N章已入库"类提示
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_importer.py -k "body_sequential or summary_body" -v`
Expected: FAIL(import_folder 不处理正文桶)

- [ ] **Step 3: 改 import_folder(第 100-151 行,正文桶单独处理)**

在 import_folder 处理完设定桶之后、返回 root 之前,加正文桶落盘(用 Task1 排序键顺序重命名):

```python
    # 正文桶:按真实章序重排、顺序归一为 第N章.md(阿拉伯章号是全系统规范);内容原样(txt 读容错落 md)
    body_files = routing.get("正文", [])
    if body_files:
        from .cnnum import chapter_order_key
        (root / paths.BODY_DIR).mkdir(parents=True, exist_ok=True)
        ordered = sorted(body_files, key=chapter_order_key)
        used: dict[str, int] = {}
        for i, fname in enumerate(ordered, start=1):
            src_p = _take(fname, used)
            if src_p is None:
                continue
            _write_dir_file(src_p, paths.chapter_path(root, i))   # 复用字节直拷/GBK 转码;目标名=第i章.md
```

（`_take(fname, used)` 是 import_folder 内既有游标闭包;`_write_dir_file` 复用既有编码容错。`.txt` 源经 `_write_dir_file`:UTF-8 字节直拷、GBK 转码——落盘目标是 `.md` 路径,内容原样。）

- [ ] **Step 4: 改 import_summary(第 154-175 行)补正文提示**

在 notes 组装处追加:

```python
    body_n = len(list((root / paths.BODY_DIR).glob("第*章.md")))
    if body_n:
        notes.append(f"{body_n} 章正文已入库(按章序重排为 第1~{body_n}章)。")
        notes.append("导入的章不能 learn 属正常(learn 只学 AI 稿→你的手改,导入章没有 AI 原稿)。")
        notes.append("建议对最近几章跑一次「除虫」铺状态账本(可选,不强制)。")
```

（`placed` 已含正文桶因 BUCKETS 加了它;`import_summary` 里 `placed = {b: len(routing.get(b, [])) for b in BUCKETS}` 自动带上正文。）

- [ ] **Step 5: 跑测试确认通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_importer.py -v && .venv/bin/python -m pytest -q`
Expected: 全过

- [ ] **Step 6: 提交**

```bash
git add loom/importer.py tests/test_importer.py
git commit -m "feat(import): import_folder 吞正文——按 chapter_order_key 重排顺序归一 第N章.md,txt 落 md;import_summary 补正文三句"
```

---

### Task 4: diagnose.py scan(读采样章 → cheap LLM 出三段候选,带出处,不落盘)

**Files:**
- Create: `loom/diagnose.py`
- Modify: `loom/usecases.py`(加 `diagnose_scan` 用例)
- Test: `tests/test_diagnose.py`

**Interfaces:**
- Consumes: `paths.chapter_path/chapter_numbers`、`chaptertext.strip_title`、`parse.split_brain_draft`、`backends.cheap_backend/get_backend`、`config.load_config`、`journey.writing_unlocked`
- Produces:
  - `diagnose.scan(root: Path, backend) -> dict`——`{"世界观": str, "人物卡": str, "卡章纲": str}`(缺段不进;**不落盘**);采样前3章+最近2章;失败/空 → `{}`
  - `usecases.diagnose_scan(root) -> dict`——薄封装(cheap 后端 + scan);仅当有正文章 + 有未达标段时有意义(调用方判)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_diagnose.py
"""整书诊断 scan:读采样正文,cheap LLM 出三段候选(带出处),不落盘。"""
from pathlib import Path

from loom import diagnose, paths
from conftest import FakeBackend, const

_CANDIDATE = (
    "===世界观===\n## 金手指\n重生带着前世记忆(第1章:「他记得三年后的那一刀」)。\n"
    "===人物卡===\n## 主角 · 沈砚\n矿场少年,重生复仇(第1章)。\n"
    "===卡章纲===\n- 第1章:雪夜矿场重生,记忆觉醒。\n"
)


def _seed_chapters(project, n=3):
    for i in range(1, n + 1):
        p = paths.chapter_path(project, i); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# 第{i}章\n\n沈砚在矿场，记得三年后的那一刀。\n", encoding="utf-8")


def test_scan_returns_three_section_candidates_no_write(project):
    _seed_chapters(project)
    before = (project / "外置大脑/世界观").glob("*.md")
    before_names = {f.name for f in before}
    out = diagnose.scan(project, FakeBackend(const(_CANDIDATE)))
    assert "金手指" in out["世界观"]
    assert "沈砚" in out["人物卡"]
    assert out["卡章纲"].startswith("- 第1章")
    # 不落盘:世界观目录没多出文件
    after_names = {f.name for f in (project / "外置大脑/世界观").glob("*.md")}
    assert after_names == before_names


def test_scan_samples_reads_body(project):
    _seed_chapters(project, 5)
    fake = FakeBackend(const(_CANDIDATE))
    diagnose.scan(project, fake)
    # 采样进了 prompt:user 里带正文关键词
    assert any("沈砚" in user for _, user in fake.calls)


def test_scan_garbage_returns_empty(project):
    _seed_chapters(project)
    assert diagnose.scan(project, FakeBackend(const("好的我来帮你分析一下这本书。"))) == {}


def test_scan_no_chapters_returns_empty(project):
    assert diagnose.scan(project, FakeBackend(const(_CANDIDATE))) == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_diagnose.py -v`
Expected: FAIL,`ModuleNotFoundError: loom.diagnose`

- [ ] **Step 3: 写 diagnose.py**

```python
# loom/diagnose.py
"""整书诊断:读已写小说的采样章,cheap LLM 把已有设定提炼成候选(带正文出处),不落盘。

红线(spec §7 / ADR 0014 诊断四边界):
- 候选只从作者正文提炼、逐条带出处(第N章),有出处=提炼、无出处=发明;
- 确认前不落盘(本模块只 return 候选,commit 在别处);
- 立项段永不进诊断(正文无平台/对标意图);
- 走 cheap_model,不沾指纹/voice。
"""

from __future__ import annotations

from pathlib import Path

from . import paths
from .chaptertext import strip_title
from .parse import split_brain_draft

_SAMPLE_HEAD = 3   # 前 3 章(定人设/金手指)
_SAMPLE_TAIL = 2   # 最近 2 章(定当前状态)
_MAX_CHARS = 2600  # 出题预算(仿 draft)

_SYSTEM = (
    "你是写作助手的记录员。作者给你他已写好的小说正文片段,你要把正文里**已经存在**的设定"
    "提炼成可落盘的资料卡。红线:只写正文里有的,逐条在括号里标出处(第N章);正文没写的绝不编造。\n"
    "严格按三段输出,用分隔标记隔开,每段可直接落盘的中文 Markdown;某段正文里看不出就整段留空:\n"
    "===世界观===\n(## 小节标题 + 正文;如力量体系/金手指/地理势力,各条带(第N章)出处)\n"
    "===人物卡===\n(## 主角 · 名字 / ## 配角 · 名字 / ## 反派 · 名字,各挂人物要点,带(第N章)出处)\n"
    "===卡章纲===\n(- 第N章:这章讲了什么,一行一章)\n"
    "不要写立项卡/平台/题材(正文里没有)。"
)


def _sample_chapters(root: Path) -> str:
    nums = paths.chapter_numbers(root)
    if not nums:
        return ""
    picked = sorted(set(nums[:_SAMPLE_HEAD] + nums[-_SAMPLE_TAIL:]))
    parts = []
    for n in picked:
        p = paths.chapter_path(root, n)
        if p.is_file():
            body = strip_title(p.read_text(encoding="utf-8")).strip()
            parts.append(f"【第{n}章】\n{body}")
    return "\n\n".join(parts)


def scan(root: Path, backend) -> dict:
    """读采样章 → LLM 出三段候选 dict(世界观/人物卡/卡章纲);不落盘。失败/空/无章 → {}。"""
    from .backends import LoomBackendError
    sample = _sample_chapters(root)
    if not sample:
        return {}
    user = f"作者已写好的小说正文(采样):\n\n{sample}\n\n按三段格式,把正文里已有的设定提炼成候选。"
    try:
        raw = backend.complete(_SYSTEM, user, max_chars=_MAX_CHARS)
    except LoomBackendError:
        return {}
    return split_brain_draft(raw)   # {"世界观":..,"人物卡":..,"卡章纲":..},缺段不进;不成三段则 {}
```

usecases 加封装(顶部 import 区已有 journey_mod/cheap_backend/get_backend/load_config):

```python
def diagnose_scan(root: Path | str) -> dict:
    """整书诊断:读采样正文出候选(不落盘)。评估类走 cheap_model。"""
    root = Path(root)
    from . import diagnose
    cfg = load_config(root)
    return diagnose.scan(root, cheap_backend(cfg) or get_backend(cfg))
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `.venv/bin/python -m pytest tests/test_diagnose.py -v && .venv/bin/python -m pytest -q`
Expected: 全过

- [ ] **Step 5: 提交**

```bash
git add loom/diagnose.py loom/usecases.py tests/test_diagnose.py
git commit -m "feat(diagnose): 整书诊断 scan——读前3+最近2章,cheap LLM 出三段候选(带第N章出处),不落盘"
```

---

### Task 5: diagnose commit 落盘(候选确认 → 复用落盘器跳过 _digest + 主角指认)

**Files:**
- Modify: `loom/diagnose.py`(加 `commit`)
- Modify: `loom/journey.py`(抽出 `_apply_card_lines(root, body) -> str`,`_land_card_lines` 改调它)
- Modify: `loom/usecases.py`(加 `diagnose_commit`)
- Test: `tests/test_diagnose.py`(追加)

**Interfaces:**
- Consumes: `draft._write_sections_into_dir`、`journey._apply_card_lines`(抽出)、`paths.WORLD_DIR_REL/CHARS_DIR_REL`
- Produces:
  - `journey._apply_card_lines(root: Path, body: str) -> str`(把已整形的 `- 第N章:` body 落卡章纲,`_land_card_lines` 的 digest 之后逻辑抽出)
  - `diagnose.commit(root: Path, picks: dict) -> dict`——`picks={"世界观":str,"人物卡":str,"卡章纲":str,"protagonist":str}`;落盘复用人写优先通道,**不调 _digest**;主角指认:`protagonist` 指明哪张是主角 → 落盘时该卡命名 `主角·名字.md`;返回 `{"landed": [...rel]}`
  - `usecases.diagnose_commit(root, picks) -> dict`(write_lock 封装)

- [ ] **Step 1: 抽出 `_apply_card_lines`(journey.py,先重构不改行为)**

把 `_land_card_lines`(journey.py:393)里 `_digest` 之后的落盘循环抽成独立函数,`_land_card_lines` 改为调它:

```python
def _apply_card_lines(root: Path, body: str) -> str:
    """把已整形的「- 第N章:…」body 落卡章纲(填空章行/追加缺章行/非章行精确判重;人写行绝不覆盖)。"""
    p = root / paths.CARD_REL
    text = p.read_text(encoding="utf-8") if p.is_file() else "# 卡章纲\n"
    landed_any = False
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("- ") or line == "-":
            continue
        m = re.match(r"^-\s*第(\d+)章[:：]\s*(.*)$", line)
        if m and m.group(2).strip():
            n, content = m.group(1), m.group(2).strip()
            empty_pat = re.compile(rf"^-\s*第{n}章[:：]\s*$", re.M)
            if empty_pat.search(text):
                text = empty_pat.sub(f"- 第{n}章:{content}", text, count=1); landed_any = True
            elif not re.search(rf"^-\s*第{n}章[:：]\s*\S", text, flags=re.M):
                text = text.rstrip() + f"\n- 第{n}章:{content}\n"; landed_any = True
        elif re.search(rf"^{re.escape(line)}\s*$", text, flags=re.M) is None:
            text = text.rstrip() + f"\n{line}\n"; landed_any = True
    if not landed_any and body.strip():
        text = text.rstrip() + f"\n{_bulleted(body)}\n"
    atomic_write_text(p, text)
    return paths.CARD_REL


def _land_card_lines(root: Path, question: str, answer: str, backend) -> str:
    body = _digest(backend, question, answer,
                   "整理成卡章纲行:每行「- 第N章:这章完成什么+章末钩子」;不属于具体某章的规划(如全书大弧),输出「- 大弧:一句话」。")
    if not body:
        body = _bulleted(answer)
    return _apply_card_lines(root, body)
```

（行为等价:原来 `if not landed_any:` 兜底追加 `_bulleted(answer)`;抽出后兜底改追加 `_bulleted(body)`——body 已是 `_bulleted(answer)`(digest 失败时)或 digest 产物,语义一致。跑 `tests/test_journey.py` 确认卡章纲落盘用例全过。）

- [ ] **Step 2: 写失败测试(追加 test_diagnose.py)**

```python
def test_commit_lands_candidates_skipping_digest(project):
    # commit 直接落已整形候选,不调 LLM(backend 传 None 也能落 sections/card_lines)
    from loom import diagnose
    picks = {
        "世界观": "## 金手指\n重生记忆。",
        "人物卡": "## 主角 · 沈砚\n矿场少年。",
        "卡章纲": "- 第1章:雪夜重生。",
        "protagonist": "沈砚",
    }
    out = diagnose.commit(project, picks)
    assert (project / "外置大脑/世界观/金手指.md").is_file()
    assert (project / "外置大脑/人物/主角·沈砚.md").is_file()   # 主角指认落对名
    assert "第1章:雪夜重生" in (project / "外置大脑/卡章纲.md").read_text(encoding="utf-8")


def test_commit_does_not_overwrite_human_file(project):
    from loom import diagnose
    human = project / "外置大脑/世界观/金手指.md"
    human.write_text("# 金手指\n\n我手写的,别动。\n", encoding="utf-8")
    diagnose.commit(project, {"世界观": "## 金手指\nAI 提炼的。", "人物卡": "", "卡章纲": "", "protagonist": ""})
    assert "我手写的,别动" in human.read_text(encoding="utf-8")   # 人写优先,不覆盖
    assert "AI 提炼的" not in human.read_text(encoding="utf-8")   # 撞人写成品 → 进访谈补充,不进原文件


def test_commit_unlocks_gate(project):
    from loom import diagnose, journey, paths
    # 先造正文章(有章)+ 立项(建书代落场景外,手补一格)
    (project / paths.PROJECT_CARD_REL).write_text("# 立项卡\n\n## 题材\n重生\n", encoding="utf-8")
    diagnose.commit(project, {
        "世界观": "## 金手指\n重生记忆。", "人物卡": "## 主角 · 沈砚\n少年。",
        "卡章纲": "- 第1章:重生。", "protagonist": "沈砚"})
    ok, missing = journey.writing_unlocked(project)
    assert ok is True and missing == []   # 四项齐,门禁开
```

- [ ] **Step 3: 写 diagnose.commit**

```python
def commit(root: Path, picks: dict) -> dict:
    """把作者确认的候选落盘:世界观/人物走 _write_sections_into_dir(人写优先),卡章纲走 _apply_card_lines;
    主角指认:picks['protagonist'] 指明主角名 → 该人物节改名 ## 主角 · 名字,落成 主角·名字.md。立项永不碰。"""
    from .draft import _write_sections_into_dir
    from .journey import _apply_card_lines
    landed = []
    world = (picks.get("世界观") or "").strip()
    if world:
        got = _write_sections_into_dir(root, paths.WORLD_DIR_REL, "\n" + world, drop_unnamed=False)
        landed += [f"{paths.WORLD_DIR_REL}/{n}.md" for n in got]
    chars = _reheader_protagonist(picks.get("人物卡") or "", (picks.get("protagonist") or "").strip())
    if chars.strip():
        got = _write_sections_into_dir(root, paths.CHARS_DIR_REL, "\n" + chars, drop_unnamed=True)
        landed += [f"{paths.CHARS_DIR_REL}/{n}.md" for n in got]
    card = (picks.get("卡章纲") or "").strip()
    if card:
        landed.append(_apply_card_lines(root, card))
    return {"landed": landed}


def _reheader_protagonist(chars_body: str, protagonist: str) -> str:
    """把候选人物卡里名为 protagonist 的那节标题归一为「## 主角 · 名字」(主角谓词要这个命名)。"""
    if not protagonist:
        return chars_body
    import re as _re
    def _fix(m):
        head = m.group(0)
        return f"## 主角 · {protagonist}" if protagonist in head else head
    return _re.sub(r"^##\s*[^\n]*$", _fix, chars_body, flags=_re.M)
```

usecases 加封装:

```python
def diagnose_commit(root: Path | str, picks: dict) -> dict:
    root = Path(root)
    with write_lock(root):
        from . import diagnose
        return diagnose.commit(root, picks)
```

- [ ] **Step 4: 跑测试确认通过 + journey 回归 + 全量**

Run: `.venv/bin/python -m pytest tests/test_diagnose.py tests/test_journey.py -v && .venv/bin/python -m pytest -q`
Expected: 全过(卡章纲抽出无行为漂移)

- [ ] **Step 5: 提交**

```bash
git add loom/diagnose.py loom/journey.py loom/usecases.py tests/test_diagnose.py
git commit -m "feat(diagnose): commit 落盘——复用_write_sections_into_dir/抽出的_apply_card_lines跳过_digest;主角指认改名主角·名字;人写优先不覆盖"
```

---

### Task 6: server 诊断端点 + 前端「从正文提炼设定」动作 + 一屏确认

**Files:**
- Modify: `loom/server.py`(加 scan/commit 两端点)
- Modify: `loom/webui/app.js`(面板动作按钮 + 诊断确认屏 + commit 刷新)
- Modify: `loom/webui/index.html`(诊断确认 overlay)+ `loom/webui/style.css`
- Modify: `loom/usecases.py`(project_state 加 `has_body`——是否有正文章,供前端判按钮出现)
- Test: `tests/test_diagnose.py`(端点冒烟)

**Interfaces:**
- Consumes: `usecases.diagnose_scan/diagnose_commit`;前端既有 `jreq/toast/showGuide/jcBtn/paintJourney/refresh`;确认屏复用 `.fr-*` 形态
- Produces: `POST /api/diagnose/scan {root}` → `{ok, candidates:{世界观,人物卡,卡章纲}}`;`POST /api/diagnose/commit {root, picks}` → project_state;`project_state` 加 `"has_body": bool`

- [ ] **Step 1: project_state 加 has_body(usecases.py)**

return dict 里(chapters 旁)加:

```python
        "has_body": bool(chapters),   # 有正文章(诊断动作出现条件之一)
```

- [ ] **Step 2: server 两端点(server.py,journey 端点附近)**

```python
class DiagnoseCommitBody(BaseModel):
    root: str
    picks: dict = {}


@app.post("/api/diagnose/scan")
def diagnose_scan_ep(b: RootBody):
    try:
        return {"ok": True, "candidates": usecases.diagnose_scan(Path(b.root))}
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)


@app.post("/api/diagnose/commit")
def diagnose_commit_ep(b: DiagnoseCommitBody):
    try:
        usecases.diagnose_commit(Path(b.root), b.picks)
        return usecases.project_state(Path(b.root))
    except (LoomBackendError, ValueError, FileNotFoundError) as e:
        return _err_json(e)
```

- [ ] **Step 3: 端点冒烟测试(追加 test_diagnose.py,TestClient + monkeypatch cheap 后端)**

```python
def test_diagnose_endpoints(project, monkeypatch):
    from fastapi.testclient import TestClient
    from loom import server, usecases, paths
    from conftest import FakeBackend, const
    for i in (1, 2):
        p = paths.chapter_path(project, i); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# 第{i}章\n\n沈砚在矿场。\n", encoding="utf-8")
    fake = FakeBackend(const("===世界观===\n## 金手指\n重生记忆。\n===人物卡===\n## 主角 · 沈砚\n少年。\n===卡章纲===\n- 第1章:重生。\n"))
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: fake)
    c = TestClient(server.app, base_url="http://127.0.0.1")
    r = c.post("/api/diagnose/scan", json={"root": str(project)})
    assert r.status_code == 200 and "金手指" in r.json()["candidates"]["世界观"]
    picks = {**r.json()["candidates"], "protagonist": "沈砚"}
    r2 = c.post("/api/diagnose/commit", json={"root": str(project), "picks": picks})
    assert r2.status_code == 200
    assert (project / "外置大脑/人物/主角·沈砚.md").is_file()
```

- [ ] **Step 4: 前端面板动作 + 确认屏(app.js)**

paintJourney 的 body 分支里(未接模型分支之后),加诊断入口——仅当**有正文章且未解锁**(`DATA.has_body && DATA.writing_unlocked === false`):

```js
  if (DATA.has_body && DATA.writing_unlocked === false) {
    body.appendChild(jcBtn("✨ 从正文提炼设定", startDiagnose));
  }
```

新增(app.js,postJourney* 附近):

```js
async function startDiagnose() {
  const root = DATA && DATA.root;
  if (!root) return;
  toast("正在读你的正文提炼设定,稍候…");
  let out;
  try {
    out = await jreq("POST", "/api/diagnose/scan", { root });
  } catch (e) { return toast(e.message, true); }
  if (!DATA || DATA.root !== root) return;
  const cand = out.candidates || {};
  if (!cand.世界观 && !cand.人物卡 && !cand.卡章纲) {
    return toast("正文里没提炼出可用设定,直接在伙伴面板答几题吧");
  }
  showDiagnoseConfirm(cand);
}

function showDiagnoseConfirm(cand) {
  const box = $("diag-body"); box.innerHTML = "";
  const SEG = [["世界观", "世界观"], ["人物卡", "人物卡"], ["卡章纲", "卡章纲"]];
  SEG.forEach(([key, label]) => {
    const val = cand[key] || "";
    const wrap = document.createElement("div"); wrap.className = "diag-seg";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!val.trim();
    cb.dataset.seg = key; cb.disabled = !val.trim();
    const h = document.createElement("label"); h.className = "diag-seg-head";
    h.appendChild(cb); h.appendChild(document.createTextNode(" " + label + (val.trim() ? "" : "(正文没提炼到)")));
    const ta = document.createElement("textarea"); ta.className = "diag-seg-text"; ta.dataset.seg = key;
    ta.value = val; ta.rows = Math.min(10, (val.split("\n").length || 1) + 1);
    wrap.appendChild(h); wrap.appendChild(ta); box.appendChild(wrap);
  });
  const pro = $("diag-protagonist"); if (pro) pro.value = "";
  $("diagnose-overlay").classList.remove("hidden");
}

async function commitDiagnose() {
  const root = DATA && DATA.root;
  if (!root) return;
  const picks = { protagonist: ($("diag-protagonist") && $("diag-protagonist").value.trim()) || "" };
  document.querySelectorAll("#diag-body .diag-seg").forEach((seg) => {
    const cb = seg.querySelector("input[type=checkbox]");
    const ta = seg.querySelector("textarea");
    picks[cb.dataset.seg] = cb.checked ? ta.value : "";
  });
  let d;
  try { d = await jreq("POST", "/api/diagnose/commit", { root, picks }); }
  catch (e) { return toast(e.message, true); }
  $("diagnose-overlay").classList.add("hidden");
  if (!DATA || DATA.root !== root) return;
  toast("已预填 → 缺的领航员会接着问");
  enterProject(d);   // 刷新 project_state:签名失配、领航员只问真缺、门禁可能已开
}
```

绑定(bind() 里):`$("diag-commit").onclick = commitDiagnose; $("diag-cancel").onclick = () => $("diagnose-overlay").classList.add("hidden");`

- [ ] **Step 5: index.html + style.css 诊断 overlay**

index.html(folder-overlay 附近)加:

```html
<div id="diagnose-overlay" class="overlay hidden">
  <div class="run-card settings-card">
    <h3>从正文提炼设定</h3>
    <p class="hint">这些是 Loom 从你正文里提炼的设定候选(带出处)。勾选要接受的、可改;不对的取消勾选。立项要你自己填,这里不提炼。</p>
    <div id="diag-body"></div>
    <label class="field-label">哪个是主角?(填名字,落成「主角·名字」卡)</label>
    <input id="diag-protagonist" type="text" placeholder="如:沈砚" />
    <div class="row-end">
      <button id="diag-cancel" class="ghost">取消</button>
      <button id="diag-commit" class="primary">确认预填</button>
    </div>
  </div>
</div>
```

style.css 加:

```css
.diag-seg { margin: var(--space-2) 0; }
.diag-seg-head { font-weight: 600; display: block; margin-bottom: 4px; }
.diag-seg-text { width: 100%; font: inherit; border-radius: 8px; padding: 6px 8px;
  border: 1px solid rgba(127,127,127,0.35); background: transparent; color: inherit; resize: vertical; }
```

- [ ] **Step 6: 验证 + 全量**

Run: `node --check loom/webui/app.js && .venv/bin/python -m pytest tests/test_diagnose.py -v && .venv/bin/python -m pytest -q`
Expected: 全过(控制者随后 preview 冒烟:导入一本带正文的书→面板「从正文提炼设定」→确认屏→预填→门禁进度)

- [ ] **Step 7: 提交**

```bash
git add loom/server.py loom/webui/app.js loom/webui/index.html loom/webui/style.css loom/usecases.py tests/test_diagnose.py
git commit -m "feat(diagnose): 端点+前端——面板「从正文提炼设定」动作(有正文+未解锁才出)+一屏勾选确认+主角指认+commit刷新回补"
```

---

### Task 7: 文档收口(CONTEXT 词表 + 导入文案 + spec 二期实现备注)

**Files:**
- Modify: `CONTEXT.md`(导入铺底词条补正文 + 加「整书诊断」词条)
- Modify: `docs/使用教程.md`(导入小节补「导入已写小说 + 提炼设定」)
- Modify: `docs/superpowers/specs/2026-07-12-startup-completeness-gate-design.md`(二期实现备注)
- Modify: `loom/webui/index.html`(folder-overlay 标题/提示补「或已写好的小说」)

**Interfaces:** 无代码。

- [ ] **Step 1: CONTEXT.md 导入铺底词条补正文**

「导入铺底」词条(约 31 行)补一句:导入现也吞**正文章节**(`.txt`/`.md`,按章序重排为 `第N章.md`,内容原样);导入章无 AI 快照(不能 learn 属正常)。

- [ ] **Step 2: CONTEXT.md 加「整书诊断」词条(照既有词条格式)**

```markdown
**整书诊断**:
进书后伙伴面板的独立动作「从正文提炼设定」——`diagnose.py` 读采样正文(前 3 + 最近 2 章)、cheap LLM 把**正文里已有**的主角/世界观/章纲提炼成候选(**逐条带第N章出处**,有出处=提炼、无出处=发明),**确认前不落盘**;作者一屏勾选/改写 → 复用人写优先落盘器写外置大脑(跳过 _digest;撞人写成品进访谈补充,绝不覆盖);主角指认落 `主角·名字.md`。落盘后签名失配、领航员只问真缺、门禁自动开。**立项段永不进诊断**(正文无平台/对标意图,守 ADR 0011 不回写)。
_Avoid_: importer 里调 LLM(零 LLM 红线,诊断是导入后的独立动作);直接 atomic_write 外置大脑(必先候选+确认);诊断碰立项卡;LLM 选正文切点(归拆章工具)
```

- [ ] **Step 3: 教程 + index.html 文案**

- `docs/使用教程.md` 导入相关小节补一句:已写好的小说(txt/md 一章一文件)也能「导入资料夹」接进来,进书后点伙伴面板「从正文提炼设定」让 Loom 把已有设定提炼出来、你确认后预填,缺的再答几题就能开写。
- `loom/webui/index.html` folder-overlay 标题/提示(约 313 行)补「或已写好的小说」:提示语改为「选一个装着你已有设定/大纲/章纲、或已写好的小说(txt/md)的文件夹……」。

- [ ] **Step 4: spec 二期实现备注(文件末尾追加)**

```markdown
---
二期实现备注(2026-07-12):导入正文桶 + `第N章.md` 顺序归一(`cnnum.chapter_order_key` 按真实章序重排)+ `.txt` 仅正文放行;`diagnose.py` scan(前3+最近2章、cheap、三段候选带出处、不落盘)/commit(复用 `_write_sections_into_dir`+抽出的 `journey._apply_card_lines`、跳过 _digest、主角指认)。v1 一文件一章;大 txt 切分与 LLM 切点归拆章工具(未做)。
```

- [ ] **Step 5: 全量回归 + 提交**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿

```bash
git add CONTEXT.md docs/使用教程.md docs/superpowers/specs/2026-07-12-startup-completeness-gate-design.md loom/webui/index.html
git commit -m "docs(diagnose): CONTEXT 加整书诊断词条+导入铺底补正文;教程/导入文案补已写小说;spec 二期实现备注"
```

---

## 计划自审记录

- **Spec 覆盖(§6 导入吞正文 / §7 整书诊断 / §9 二期清单)**:正文桶+.txt+机械重命名(T1 cnnum + T2 路由 + T3 落盘)✓;diagnose scan 采样/cheap/三段候选/带出处/不落盘(T4)✓;commit 复用落盘器跳过_digest/主角指认/立项不碰/人写优先(T5)✓;面板动作(有正文+未达标才出)/一屏确认/回补汇合(T6)✓;ndjson 进度——**降级为 toast+同步 scan**(诊断单次 cheap 调用秒级,一屏确认前不需要流式;spec 的 ndjson 进度留作后续,已在文档标注)——注:这是对 spec「跑长走 ndjson」的**有意简化**,单次 cheap 调用无需流式,列此说明供终审裁。文档(T7)✓。
- **占位符扫描**:无 TBD;每步给完整代码或确切改法。cn_to_int 的清理在 T1 Step 4 显式给最终形态。
- **类型一致性**:`diagnose.scan(root,backend)->dict`(T4)与 `commit(root,picks)->dict`(T5)、usecases 封装、端点(T6)签名一致;`picks` 键(世界观/人物卡/卡章纲/protagonist)前后端一致;`_apply_card_lines(root,body)->str`(T5 抽出)被 `_land_card_lines` 与 diagnose.commit 共用。
- **红线**:importer 零 LLM(诊断独立)、确认前不落盘、立项不碰、主角硬判命名、cheap 路由、导入正文不造快照(门禁照拦)——全在 Global Constraints + 各任务重申。
