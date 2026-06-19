# T9-deconstruct · 拆书引擎:离线 skill + loom deconstruct 命令(只抽可迁移框架、剥专名、产物供人确认,绝不回流指纹/canon)
- **类型**: hybrid　**工作量**: small　**批次**: 批次1 · 零风险即做(纯内容/隔离小代码)
- **依赖**: 无
- **涉及文件**:
  - `loom/templates/skills/拆书.md(新增,内容=distilledContent)`
  - `loom/deconstruct.py(新增,纯逻辑,内容=codeSketch 上半)`
  - `loom/cli.py(修改,在 :154 status 后、:156 version 前插入 deconstruct 子命令)`

## 问题(Loom 现状)

Loom 现在没有任何"从参考书提炼可迁移套路"的能力。作者想"对标某本爽文写"时,只能凭空手填 外置大脑/世界观.md(loom/templates/外置大脑/世界观.md:14 金手指、:9 力量体系都是空占位),没有方法论辅助。

但这是把双刃刀,风险极高:拆书天然产出"剧情套路/金手指机制/爽点循环",一旦喂错地方就违背 Loom 的灵魂——
① 红线①:套路(管 what)若进了 写手/写作指纹(管 voice),"像你"立刻被污染成"像那本书";
② 红线②:AI 拆出来的东西若直接写进 外置大脑/世界观.md(canon),作者的世界就被原作事实/专名灌进来,失去"人维护、file-as-truth"。

现状接入点(精确到 file:line):
- loom/cli.py:21 是 typer app(`app = typer.Typer(...)`),现有命令为 init/seed/write/learn/status/version(各 @app.command)。各命令统一用 find_project_root()(loom/config.py:20)定位项目根,用 get_backend(load_config(root))(loom/backends.py:170)取后端,Backend.complete(system, user, max_chars)(loom/backends.py:21)是唯一生成接口。还没有 deconstruct 子命令。
- loom/templates/skills/ 下已有 6 个手艺 skill(世界观引擎/故事引擎/黄金开篇/网文大神/去AI味/评估自检),无"拆书.md"。skill 是纯 Markdown 方法论,被 agent 的 YAML reads: 声明引用(见 templates/agents/设定师.md:3-8 reads: skills/世界观引擎.md)。
- 拆书产物的人工归属地:外置大脑/世界观.md(canon),由人手动 merge。设定师.md:3-8 的 reads: 只读 世界观.md/人物卡.md,不读拆书产物——这正是物理隔离的天然边界。

## 从 webnovel-writer 借什么 / 丢什么

借鉴源:/tmp/webnovel-writer/webnovel-writer/agents/deconstruction-agent.md(已真实读完 144 行)。

【抽精华】(核心是它的防污染边界,正是 Loom 拆书的命脉):
- §3 输出边界(行 36-41):"本 agent 只返回结构化结果,不写任何文件""严禁创建、写入或修改 设定集/大纲/正文 及任何 story canon"——Loom 据此让 deconstruct 只写到隔离区 外置大脑/.拆书/,绝不碰 世界观.md/正文/写作指纹.md。
- §6 抽象转化规则(行 74-85):"抽离条件框架,保留'什么条件组合造成爽感/期待/反差',不保留原作人物/地点/组织/能力名和具体事件";"识别核心梗边界";"每个可借结构都说明如何换题材/换人物/换金手指/换情绪方向"——这是 Loom skills/拆书.md 方法论主体。
- §6 末尾禁止项(行 85):"禁止只拆具体桥段不拆条件框架;把原作金句/设定名/角色关系/名场面当 init 候选"——Loom 直接收录为 skill 的"禁止"段。
- §7 Schema 的 do_not_copy[] 与 canon_contamination_warnings[](行 102、108):原作专名/名场面/金句必须列进黑名单——Loom 复用为产物里的"剥离清单/专名黑名单"。
- §9 用户确认(行 134):候选必须标注"需用户确认后才采用";相似度高的进 canon_contamination_warnings——Loom 复用为"产物=候选,人确认后手动 merge"。

【明确丢弃】(都是 CC 依赖/重基础设施/解析层,违背 Loom 反过度工程红线③):
- §2/§5 的 quick/deep 双模式 + 阶段0-5 逐章解析、章节边界识别、分块、resume_state、_progress.md(行 21-72)——这是为长文流水线设计的重解析层。Loom 不要,只做"读文本→抽框架→剥专名"一遍过,文本能读多少抽多少。
- §3 tools: Read/Grep/Bash 与 §8 SubagentRun(行 35、114-123)——CC/子代理基础设施。Loom 无 hook、无子代理,直接用 backends.complete。
- §5 confidence/coverage/overlap 的数值质量门控与孤立情节兜底算法(行 67-72)——打分引擎,红线③禁止。只保留"低置信就提示人复核"的朴素思想,不抄算法。
- §7 庞大的 init_reference_research JSON 顶层 schema——Loom 产物是人能直接读改的 Markdown,不是机器 JSON。

## Loom 落地设计

两部分:一个离线 skill(内容型,见 distilledContent)+ 一个 loom deconstruct 子命令(代码型,见 codeSketch)。

【命令落点】loom/cli.py:
- 在 status 命令后(约 :154 之后)、version 之前,新增 @app.command deconstruct,签名 `deconstruct(source: Path, name: str = typer.Option(None, "--名", "--name"))`。
- 复用现有三件套:root = find_project_root();config = load_config(root);backend = get_backend(config)。错误统一走已有的 `except (LoomBackendError, FileNotFoundError, ValueError) as e: _die(str(e))` 模式(与 seed/write/learn 一致)。
- 新建 loom/deconstruct.py,放纯逻辑函数 `deconstruct(root, source_text, name, backend, render)`,与 fingerprint.py 同构(cli.py 只做 IO 与渲染,逻辑在独立模块,符合现有分层)。
- skill 文本作为 system prompt 的方法论来源:deconstruct.py 读 root/"skills"/"拆书.md"(项目实例化后的副本,init 时由 scaffold.py:23 的 copytree 从 templates 拷入)。若项目里没有(老项目),回退读包内 templates/skills/拆书.md。

【数据流 / 物理隔离(红线②落地)】:
1. 命令读 source 文件文本(纯本地 IO,不联网抓取);
2. system = 拆书.md 全文 + 硬护栏(只输出可迁移框架、剥专名、Markdown);user = 参考文本;调 backend.complete;
3. 产物只落到 root/"外置大脑"/".拆书"/(隔离草稿区,带点前缀,与 正文/.原稿 同款隐藏约定),文件名 `{name或source.stem}-拆解.md`;
4. 绝不写 外置大脑/世界观.md、外置大脑/写作指纹.md、正文/。命令末尾 _render 一条 info 明确提示:"产物在 外置大脑/.拆书/,只是候选;要用请你亲手把'条件框架'抄进 世界观.md,专名黑名单别抄。"

【不进默认流水线(红线①落地)】:
- 不在任何 templates/agents/*.md 的 reads: 里加 skills/拆书.md。设定师.md:3-8 的 reads: 保持原样,5-agent 顺序流水线(run_pipeline,loom/agents.py)完全不引用拆书产物。deconstruct 是 cli.py 里一个孤立子命令,run_pipeline 不调它,它也不写流水线读的任何文件。
- scaffold.py 无需改逻辑:templates/skills/拆书.md 新增后,copytree(scaffold.py:23)会自动把它拷进新项目的 skills/,但因为没 agent reads 它,它只是"放在工具箱里、人想用才用"的离线工具。

## 可落盘内容(蒸馏成品)

# 拆书(离线工具 · 给"想对标某本书"的你,不给任何 agent)

> 这不是流水线的一环。没有任何 agent 会读它,也没有任何 agent 会读它的产物。
> 它是一把离线的解剖刀:把一本你想对标的参考书,拆成**可迁移的条件框架**,产物只是**候选**,要不要用、用哪条,你亲手决定。
>
> **它管 what(题材/套路/金手指机制),绝不管 voice(你的文风)。** 所以它的产物永远不会、也绝不允许进 `写作指纹.md`——那是"像你"的地方,套路进去会把你变成"像那本书"。

## 一、只准抽这个:可迁移的"条件框架"

拆书的唯一合法产物,是**剥掉原作血肉、只剩骨架的条件组合**。问的永远是"什么条件凑在一起,造成了爽/期待/反差",而不是"它写了什么事"。

逐项抽:

1. **读者承诺**:这本书一句话承诺给读者什么核心爽感(逆袭/扮猪吃虎/种田爽/复仇)?靠什么反复兑现?违背它会塌的底线是什么?
2. **开篇钩子框架**:第一章前几百字用什么**结构**抓人(绝境开局/身份落差/异象降临/倒计时)?为什么有效?——只写结构,不写它具体写了谁。
3. **爽点循环框架**:蓄压→爆发→反应→衔接,各占多少篇幅(铺放比)?反应层有几层(谁在场、谁被打脸、谁见证)?
4. **金手指的"机制形状"**:不是"它叫什么",而是【获得方式 / 激活条件 / 成长曲线 / 限制 / 代价】这五维的组合形状。例:濒死激活、用一次折寿——这是形状,可迁移;"逆息体质"是专名,扔掉。
5. **主角压力模型**:欲望是什么?缺陷/软肋怎么持续制造压力?能力靠什么"对比对象/舞台"显形?
6. **反派/压迫层级**:有几层压迫?每层的压迫类型(碾压/羞辱/规则碾压)?反派如何镜像主角(照出主角缺什么)?
7. **节奏与章末钩**:信息密度、章末用哪类钩收尾(悬念/危机/反转/期待)。
8. **核心梗边界**:哪些桥段服务核心梗,哪些一偏离就伤读者承诺——标出来,提醒自己别学偏。

每抽出一条,**必须配一句"差异化改造":换题材 / 换人物关系 / 换金手指机制 / 换情绪方向中的至少一种**,说明你要怎么用得不一样。只抄不变 = 抄书,不是借鉴。

## 二、必须剥掉:专名与原作事实(剥离清单)

产物里要单列一段 **【剥离清单 / 专名黑名单】**,把以下东西**点名列出、标记"绝不抄"**:

- 原作的角色名、地名、组织/势力名、功法/能力/金手指的专属名;
- 原作的具体剧情事件、名场面、金句原文;
- 任何"换个皮就能认出是哪本书"的设定。

列出来不是为了用,是为了**让你和后续的自己一眼认出"这是它的、不是我的",写的时候主动绕开**。相似度太高、绕不开的桥段,标【高污染·建议换核】。

## 三、禁止(把上面两条反过来钉死)

- **禁止**把套路/金手指机制/爽点循环写进 `写作指纹.md`——那是文风的地方,套路进去 = 污染"像你"。(红线①)
- **禁止**直接把产物当成你的 `世界观.md`/`人物卡.md`。产物在隔离区,是候选;要用,你**亲手**把"条件框架"抄进 canon,**专名黑名单一个字都别抄**。(红线②)
- **禁止**只写"这段写得真好""节奏不错"这种读后感——那不是框架,没有可迁移性。
- **禁止**只拆具体桥段不拆条件框架(只记"主角三招打飞反派"无用;要记"濒死触发底牌、以弱胜强、围观者重估其实力"这个**可换皮的框架**)。
- **禁止**凭记忆/常识编造原作内容。文本里没有的,就写"文本未覆盖",不猜。

## 四、产物长这样(模板)

```markdown
# 拆解:《参考书名》  ← 候选,非 canon。用前请人工挑选并改造。

## 读者承诺
- 核心爽感:
- 兑现方式:
- 不可违背的底线:

## 可迁移框架(每条都带"我要怎么改")
### 框架1 · 开篇钩子
- 条件组合:
- 为何有效:
- 我的差异化改造(换题材/人物/金手指/情绪):

### 框架2 · 爽点循环
- 铺放比 / 反应层:
- 我的差异化改造:

### 框架3 · 金手指机制形状
- 获得 / 激活 / 成长 / 限制 / 代价:
- 我的差异化改造:

（其余框架同构:主角压力模型、反派层级、节奏与章末钩……）

## 核心梗边界
- 服务核心梗的:
- 一偏就塌的:

## 【剥离清单 / 专名黑名单】绝不抄
- 角色名:
- 地名/势力:
- 金手指/能力专名:
- 名场面/金句:
- 高污染·建议换核的桥段:

## 我的判断(留给确认时填)
- 这本里我真正想借的就 ___ 条,分别是:
- 这几条我准备怎么变得不像它:
```

## 五、用法(它在工具箱里,不在流水线里)

```
loom deconstruct <参考书文本路径> [--名 自定义名]
```

产物落在 `外置大脑/.拆书/`,**只是候选**。没有任何 agent 会读它。
想用,你亲手把"条件框架"挑进 `世界观.md`——这一步是人的判断,不是 AI 的。专名黑名单留着提醒自己别抄,**永远别动 `写作指纹.md`**。

## 代码草图

# ── 新增 loom/deconstruct.py(纯逻辑,与 fingerprint.py 同构)──────────────
from __future__ import annotations
from pathlib import Path
from typing import Callable

# 硬护栏:把 backend 压成"只抽框架、剥专名、出 Markdown"的纯文本函数。
# 与 backends.ClaudeCodeBackend._GUARD 思路一致,但内容是拆书专属红线。
_GUARD = (
    "你是离线拆书工具,不是助手。只输出一份 Markdown 拆解候选,不输出别的话。\n"
    "铁律:① 只抽【可迁移条件框架】(什么条件组合造成爽/期待/反差),"
    "绝不保留原作角色名/地名/组织名/能力名/金手指专名/具体剧情/名场面/金句;\n"
    "② 必须单列一段【剥离清单/专名黑名单】把这些专名点名列出并标'绝不抄';\n"
    "③ 每条框架都要配一句'差异化改造'(换题材/人物/金手指/情绪 至少一种);\n"
    "④ 严禁写读后感,严禁凭记忆编造文本里没有的内容(没有就写'文本未覆盖')。"
)

def _load_skill(root: Path) -> str:
    """优先读项目内 skills/拆书.md(init 时由 copytree 拷入);回退包内模板。"""
    local = root / "skills" / "拆书.md"
    if local.exists():
        return local.read_text(encoding="utf-8")
    pkg = Path(__file__).parent / "templates" / "skills" / "拆书.md"
    return pkg.read_text(encoding="utf-8")

def deconstruct(root: Path, source_text: str, name: str,
                backend, render: Callable[[dict], None]) -> Path:
    if not source_text.strip():
        raise ValueError("参考书文本是空的,没东西可拆。")
    render({"type": "info", "message": f"拆书中:{name} …"})

    system = _load_skill(root) + "\n\n---\n\n" + _GUARD
    out_text = backend.complete(system, source_text, max_chars=3000)

    # 物理隔离(红线②):只写隔离草稿区,绝不碰 世界观.md / 写作指纹.md / 正文/
    out_dir = root / "外置大脑" / ".拆书"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}-拆解.md"
    out_path.write_text(out_text + "\n", encoding="utf-8")
    return out_path

# ── 接入 loom/cli.py(在 status 命令之后、version 之前,约 :154 后)──────────
# @app.command(help="离线拆一本参考书,抽可迁移框架(产物是候选,不进流水线)。")
# def deconstruct(source: Path = typer.Argument(..., help="参考书文本路径"),
#                 name: str = typer.Option(None, "--名", "--name")) -> None:
#     from .deconstruct import deconstruct as do_deconstruct
#     try:
#         root = find_project_root()
#         if not source.exists():
#             _die(f"参考书文件不存在:{source}")
#         text = source.read_text(encoding="utf-8")
#         label = name or source.stem
#         out = do_deconstruct(root, text, label, get_backend(load_config(root)), _render)
#         console.print(Panel(
#             "产物在 [bold]外置大脑/.拆书/[/bold],只是候选。\n"
#             "要用:亲手把'条件框架'抄进 世界观.md;[red]专名黑名单别抄,写作指纹.md 永远别动[/red]。",
#             title=f"✓ 已拆:{label} → {out.name}", border_style="yellow"))
#     except (LoomBackendError, FileNotFoundError, ValueError) as e:
#         _die(str(e))

## 验收标准

- [ ] loom/templates/skills/拆书.md 已新增,内容为 distilledContent 全文;init 新项目后该文件被 copytree 拷进 项目/skills/拆书.md
- [ ] loom/deconstruct.py 已新增,deconstruct() 只写到 外置大脑/.拆书/{name}-拆解.md,grep 全文件确认不写 世界观.md / 写作指纹.md / 人物卡.md / 正文/ 任一路径
- [ ] loom/cli.py 新增 deconstruct 子命令,位于 status 之后 version 之前;`loom deconstruct --help` 可显示;错误走既有 _die 收口
- [ ] 跑一次 `loom deconstruct 某文本.md`(可用 LOOM_DEMO=1 或真实文本),产物落在 外置大脑/.拆书/ 且 世界观.md / 写作指纹.md 内容字节不变
- [ ] 产物 Markdown 含【剥离清单/专名黑名单】段,且每条框架带'差异化改造'一句
- [ ] grep 全部 templates/agents/*.md,确认没有任何 agent 的 reads: 含 skills/拆书.md;run_pipeline(loom/agents.py)不引用 deconstruct 或 .拆书/ 任何文件
- [ ] 拆书命令不在默认流水线:`loom write N` 全程不触发 deconstruct,不读 .拆书/ 下任何文件

## 红线(防变味)

- ⛔ 守红线①(像你不被污染):拆书产物=套路/金手指/爽点,只能进【世界观.md(管 what)】且必须人工挑选 merge;deconstruct.py 绝不写 写作指纹.md,任何 agent 的 reads: 绝不含 skills/拆书.md,run_pipeline 绝不读 .拆书/。套路与 voice 物理隔离。
- ⛔ 守红线②(AI 产物物理隔离不回流):deconstruct 只写 外置大脑/.拆书/ 隔离草稿区(隐藏前缀,与 正文/.原稿 同款),绝不直接写 canon(世界观.md/人物卡.md);产物明确标注'候选,需人确认后亲手抄入',且产物自带'专名黑名单别抄'指引。
- ⛔ 守红线③(极简/本地/反过度工程):不引入向量库/SQLite/打分引擎/质量门控算法/CC hook/子代理;不做 quick/deep 双模式与逐章解析;一遍过、读本地文件、复用现成 backends.complete 单接口;deconstruct.py 保持薄(~40 行逻辑)。
- ⛔ 本地优先:source 是本地文件路径,绝不联网抓书;沿用 find_project_root + load_config + get_backend 既有链路,不新增配置项。
- ⛔ 离线可用:skill 是纯 Markdown,init/copytree 即得;命令在无 key 时给的是 backends 既有的友好错误(LoomBackendError),不抛栈。

