# T7-genre-library · T7-genre-library: 37 题材压一屏 → skills/题材/(hybrid), init 按选题只拷一份
- **类型**: hybrid　**工作量**: large　**批次**: 批次3 · 需用户裁决(与现有铁律/决定冲突)
- **依赖**: 无
- **涉及文件**:
  - `loom/templates/skills/题材/系统流.md (新增)`
  - `loom/templates/skills/题材/都市异能.md (新增)`
  - `loom/templates/skills/题材/<其余35个题材>.md (新增,清单见 distilledContent)`
  - `loom/templates/skills/题材/README.md (新增,别名+复合索引)`
  - `loom/scaffold.py (改:init 加 genre 参数、copytree ignore 题材目录、按选中题材单拷、别名归一)`
  - `loom/templates/agents/设定师.md (改:reads: 追加 skills/题材/<题材>.md 占位)`

## 问题(Loom 现状)

Loom 现在没有题材库。loom/templates/skills/ 只有 7 个跨书手艺技能(世界观引擎/故事引擎/网文大神/去AI味/黄金开篇/评估自检),没有任何"按题材给套路"的资产,作者只能从零想"系统流该有什么爽点/桥段/雷区"。

接入现状(精确到行):
- scaffold.py:23 用 `shutil.copytree(TEMPLATES_DIR, target, dirs_exist_ok=True)` 一把全拷整个 templates,没有"按用户选的题材只拷一份"的分支;`init(name, parent=None)`(scaffold.py:17)签名里根本没有 genre 参数,init 也没有接收题材选择的入口。
- 设定师.md:3-6 的 reads: 写死了 外置大脑/世界观.md、外置大脑/人物卡.md、skills/世界观引擎.md 三条,没有题材占位,所以即便题材库建好,流水线第一棒也读不到选中的题材卡。
- 外置大脑/世界观.md:1-24 是空占位骨架,作者要从零写,缺一份"这个题材到底要什么"的速查参考来填它。

红线约束:这份题材速查管的是 what(剧情套路/爽感/桥段),按红线①只能进设定师/世界观链路,绝不能 reads 进写手或写作指纹(那是管 voice 的"像你");按红线③绝不引入打分参数/route seed/CSV。

## 从 webnovel-writer 借什么 / 丢什么

源在 /tmp/webnovel-writer(已 clone)。

【抽内容】两处,均已 Read 验证:
1. /tmp/webnovel-writer/webnovel-writer/templates/genres/*.md(37 份,文件名见下)。每份已是"流派细分 + 核心爽点 + 经典套路 + 数值/节奏控制 + 雷区"的人话速查,正是要的"管 what 的剧情套路"。已读证据:
   - 系统流.md:核心卖点(数据可视化+任务驱动+确定性回报);数值膨胀控制阀(指数增长会崩 → 属性压缩/货币回收/边际效应);系统与宿主三阶段(工具期/伙伴期/博弈期);签到/抽奖/兑换流各自的爽点与陷阱。
   - 都市异能.md:灵气复苏三阶段(隐秘/爆发/新秩序);隐秘期硬规则(大动静必须给现实余波+遮蔽机制);势力博弈(官方/财团/教派);觉醒等级 E-S;经典爽点(扮猪吃虎/赌石鉴宝/校花保镖)。
   - 修仙.md:凡人/无敌/家族/苟道四流派各自核心爽点;黑暗森林法则(资源稀缺/杀人夺宝/怀璧其罪);大境界压制。
2. /tmp/webnovel-writer/docs/guides/genres.md:题材别名映射表(玄幻/修真→修仙、克系→克苏鲁、电竞文→电竞、直播带货→直播文)、复合题材主辅 7:3 规则、最多组合 2 个。抽成 README 索引里的别名/复合说明。

37 份文件名(直接做文件名):修仙 系统流 高武 西幻 无限流 末世 科幻 都市异能 都市日常 都市脑洞 现实题材 电竞 直播文 古言 宫斗宅斗 青春甜宠 豪门总裁 职场婚恋 民国言情 幻想言情 现言脑洞 女频悬疑 种田 年代 规则怪谈 悬疑脑洞 悬疑灵异 克苏鲁 狗血言情 替身文 知乎短篇 历史古代 历史脑洞 多子多福 抗战谍战 游戏体育 黑暗题材。

【明确丢弃】(全是绑质检/CC/解析层的基础设施):
- /tmp/webnovel-writer/webnovel-writer/references/genre-profiles.md 整份的 hook_config/coolpoint_config/micropayoff_config/pacing_config/override_config(YAML 数值参数:stagnation_threshold、debt_multiplier、HARD-003、Override 债务窗口)——这是喂 Step1.5/Context Agent/Checkers 打分引擎的,违反 Loom 红线③,全丢。
- genre_taxonomy.py、references/csv/、taxonomy/、index/ 与 route seed——CSV 解析层与绑定的质检系统,全丢。
- 模板里的"创意约束推荐 Pack M13/U03""任务生成器 Prompt""<entity> XML 标签扩展"——绑 webnovel-writer 自己的约束包/实体解析管线,Loom 没有,提炼时删掉。
- genre-profiles.md 顶部 "Fallback Only / Story Contracts / CSV route seed" 整套合同机制——丢。

## Loom 落地设计

【新增目录】loom/templates/skills/题材/<题材>.md,37 份,题材名用中文文件名(与 webnovel-writer 一致,便于作者按名选)。每份 ≤一屏(目标 ≤60 行 / ≤2KB),统一用本工单 distilledContent 的"单题材模板结构"。再加 loom/templates/skills/题材/README.md 作索引(别名映射 + 复合题材 7:3 说明,从 genres.md 蒸馏)。

【改 scaffold.py】(代码型,精确接入点):
- scaffold.py:17 函数签名 `def init(name, parent=None)` → 加参数 `genre: str | None = None`。
- 现状 scaffold.py:23 一把全拷 templates;改成:copytree 时排除整个 skills/题材/ 目录(用 shutil.copytree 的 ignore 回调跳过 题材/),拷完后若 genre 命中,只把 skills/题材/<genre>.md 单文件拷进项目的 skills/题材/<genre>.md。这样实现"只拷一份"。
- genre 解析走别名表(读 templates/skills/题材/README.md 或内置 dict):把"玄幻/修真"→"修仙"等归一;命中不到时 genre 视为 None,不报错(遵守 scaffold "永不因缺失失败"的离线铁律,见 scaffold.py:1 docstring)。
- genre=None 时:不拷任何题材文件,行为与今天完全一致(向后兼容,题材是可选增益)。
- 数据流:WebUI/CLI init 表单选题材 → init(name, parent, genre) → 项目 skills/题材/<genre>.md 落地一份(可手改、file-as-truth)。

【改 设定师.md 的 reads:】(代码/配置型):
- 设定师.md:3-6 的 reads: 列表追加一条题材占位,如 `- skills/题材/<题材>.md`(占位字面量,init 时若选了题材则该文件存在;没选则该行指向不存在文件,Agent 读取时跳过即可)。reads 只进设定师这一棒,题材内容因此只流向"圈设定边界"(管 what),物理上不进写手/润色师/写作指纹——守红线①。

不碰:写手.md / 润色师.md / 写作指纹.md / fingerprint.py 一律不加题材 reads,保证"像你"不被题材套路污染。

## 可落盘内容(蒸馏成品)

## 一、单题材模板结构(每份 skills/题材/<题材>.md 套这个骨架,≤一屏)

```markdown
# <题材>题材模板

> 给【设定师】读,用来圈这本书的剧情边界。管的是「写什么套路」(what),不碰「怎么写得像你」(voice)。
> 这是参考速查,不是铁律——和你的脑洞冲突时,以你为准,直接手改这份文件。

## 核心爽感
读者翻这本书图的那口爽气,一句话。

## 读者期待(不交付会弃书)
- 进场就预期的 3 条硬期待,缺一条读者就觉得"不对味"。

## 必备桥段(选用,别全塞)
- 这个题材的招牌场景/经典套路,3-5 条,作者按需挑。

## 常见雷区(踩了掉粉)
- 这个题材最容易写崩的 3-4 个坑 + 一句怎么绕开。

## 金手指匹配
- 这个题材的金手指长什么样、成长性、必须有的限制/代价(防无敌)。
```

> 注:金手指/桥段只写给设定师定 what,绝不进写作指纹。题材文件里不写任何打分参数(无 hook_config / 阈值 / 债务倍率),那是 webnovel-writer 的质检层,Loom 不要。

---

## 二、2 个示例题材成品(直接落盘)

### skills/题材/系统流.md

```markdown
# 系统流题材模板

> 给【设定师】读,用来圈这本书的剧情边界。管「写什么套路」(what),不碰「怎么写得像你」(voice)。
> 参考速查,不是铁律——和你的脑洞冲突时以你为准,直接手改。

## 核心爽感
数据可视化 + 任务驱动 + 确定性回报。挥剑1000次经验+10,努力立刻变成看得见的数字。

## 读者期待(不交付会弃书)
- 每次行动有即时数值反馈(战力 50→180,前后对比),不能努力了没动静。
- 系统给的任务有明确目标+奖励+失败惩罚,读者跟着"通关"。
- 升级节奏不拖,卡级太久读者会烦。

## 必备桥段(选用,别全塞)
- 新手任务开局,系统冷冰冰发布第一个强制任务。
- 签到/抽奖/兑换的高光时刻(欧皇翻盘、单车变摩托)。
- 隐藏成就触发,给读者惊喜彩蛋。
- 系统身世悬念抛出(谁造的?养蛊还是夺舍?)。

## 常见雷区(踩了掉粉)
- 数值指数膨胀→读者麻木:用属性压缩(换地图重置)、货币回收(吞金兽功能)、边际效应(高级升级变慢)压住。
- 面板刷屏:别每章贴完整属性表,只在升级/关键节点展示变化。
- 签到流写成流水账:签到必须裹在剧情里(为签到闯禁地),不是打卡日记。
- 魅力/幸运等废属性:要留就得 5-10 章内给一次可感知回报,否则别列。

## 金手指匹配
- 金手指=系统本身,既是最强外挂也是最大枷锁。
- 三阶段成长:工具期(机械发任务)→伙伴期(智能吐槽卖萌)→博弈期(主角想摆脱控制)。
- 必须有限制:主线任务失败有肉痛惩罚;商城/抽奖有积分消耗;别让系统万能到没冲突。
```

### skills/题材/都市异能.md

```markdown
# 都市异能题材模板

> 给【设定师】读,用来圈这本书的剧情边界。管「写什么套路」(what),不碰「怎么写得像你」(voice)。
> 参考速查,不是铁律——和你的脑洞冲突时以你为准,直接手改。

## 核心爽感
熟悉的现代生活 + 超凡力量入侵。在地铁、写字楼、古玩街这种平凡场景里藏着非凡。

## 读者期待(不交付会弃书)
- 现代背景的真实质感(身份/职业/社会规则可信)。
- 隐藏实力→关键时刻掉马的反差爽。
- 异能有清晰等级与分类,强弱看得懂。

## 必备桥段(选用,别全塞)
- 扮猪吃虎:被当普通学生/打工仔骑脸,一根手指碾压亮 S 级执照。
- 赌石/鉴宝捡漏(黄金瞳式):古玩街专家打眼,主角低价拿下藏灵气的宝。
- 校花/大小姐保镖,暧昧互动顺手解决追求者。
- 势力招安/通缉的抉择(官方 vs 财团 vs 教派)。

## 常见雷区(踩了掉粉)
- 隐秘期大动静没人管:出现爆炸/坍塌/封路,本章或下一章必须给"现实余波+遮蔽机制"(警戒线/删监控/官方口径=煤气爆炸)。
- 灵气复苏阶段乱跳:隐秘期→爆发期→新秩序期要有推进逻辑,别一会儿全民异能一会儿又没人知道。
- 异能体系糊:E/C/A/S 级战力要锚定(A 级一人敌一师),别忽强忽弱。

## 金手指匹配
- 金手指=觉醒的异能(元素/强化/精神/特殊系)。
- 成长走觉醒等级线 E→S,每升一级对应可见的力量跃迁。
- 限制:特殊系(空间/时间/因果)是 BUG 级,必须配冷却/消耗/反噬,否则破坏隐秘期张力。
```

---

## 三、其余 35 个题材清单 + 蒸馏方案

按上面同一模板结构,从 /tmp/webnovel-writer/webnovel-writer/templates/genres/<同名>.md 蒸馏。逐题材蒸馏动作固定为四步:
1. 提"核心卖点"那句 → 核心爽感;
2. 把"流派细分/世界观社会学"压成 3 条读者硬期待;
3. 把"经典套路/经典爽点"挑 3-5 条 → 必备桥段;
4. 把"控制阀/硬规则/陷阱"反写成 3-4 条 → 常见雷区;金手指/力量体系段 → 金手指匹配。
统一删:Pack 约束包推荐、任务生成器 Prompt、<entity> XML、所有数值参数。

35 个清单(源文件均在 genres/ 同名 .md,字号见下,均 3-8KB 足够压到一屏):
玄幻修仙/高武类:修仙、高武、西幻、无限流、末世、科幻
都市类:都市日常、都市脑洞、现实题材、电竞、直播文
言情类:古言、宫斗宅斗、青春甜宠、豪门总裁、职场婚恋、民国言情、幻想言情、现言脑洞、女频悬疑、种田、年代、狗血言情、替身文
悬疑灵异类:规则怪谈、悬疑脑洞、悬疑灵异、克苏鲁
历史类:历史古代、历史脑洞、抗战谍战
其他:多子多福、游戏体育、知乎短篇、黑暗题材

各题材蒸馏要点(从已读源文件提取的锚,确保不泛泛):
- 修仙:四流派(凡人靠算计/无敌横推/家族种田/苟道猥琐)各自爽点;黑暗森林法则;大境界压制不可逾越。雷区:境界体系崩、机缘开太多显假。
- 规则怪谈:诡异规则+生存推理+反杀。读者期待:规则自洽可推演。雷区:规则前后矛盾、主角靠运气而非破解。
- 知乎短篇:短平快+强反转+情绪冲击。期待:每章一个可感知收获、结尾反转。雷区:拖节奏、铺垫过长。
- 替身文:误解+反转+追妻火葬场。爽感:身份掉马+追悔。雷区:虐过度无糖、误会靠降智。
- 克苏鲁:未知恐惧+理智消耗+渺小感。雷区:把旧神写成可正面打的 BOSS、滥用 SAN 值梗。
- 种田:经营滚雪球+烟火气+慢爽。雷区:无冲突的流水账、节奏太平。
- 电竞/游戏体育:逆风翻盘+团队磨合+冠军追逐。期待:比赛有可追踪胜负目标。雷区:外行写技术细节穿帮。
- 直播文:实时流量反馈+舆论商业双线。雷区:数据爽点失真(无脑暴涨)。
- 其余(高武/西幻/无限流/末世/科幻/古言/宫斗宅斗/青春甜宠/豪门总裁/职场婚恋/民国言情/幻想言情/现言脑洞/女频悬疑/年代/狗血言情/悬疑脑洞/悬疑灵异/历史古代/历史脑洞/抗战谍战/多子多福/黑暗题材/都市日常/都市脑洞/现实题材):同四步法逐一蒸馏,每份独立成 ≤一屏文件。

### skills/题材/README.md(索引,从 docs/guides/genres.md 蒸馏)

```markdown
# 题材速查库

每个 .md 是一份"这个题材要什么套路"的速查,给设定师定 what 用。init 时按你选的题材只会拷一份进书。
这是参考,不是铁律——直接手改成你这本书的样子。

## 别名映射(选题材时这些会归一)
- 玄幻 / 修真 / 玄幻修仙 → 修仙
- 都市修真 → 都市异能
- 游戏电竞 / 电竞文 → 电竞
- 直播 / 主播 / 直播带货 → 直播文
- 克系 / 克系悬疑 → 克苏鲁

## 复合题材
- 想糅两个题材:主辅 7:3,主线走主题材逻辑,副题材只供钩子/规则/爽点。最多两个。
- 例:修仙+系统流、古言+宫斗宅斗、都市脑洞+规则怪谈。
- 复合时把两份题材文件都拷进来,作者自己手动取舍。
```

## 代码草图

## scaffold.py 改造(接入点:scaffold.py:13 常量区、:17 签名、:23 copytree)

```python
# 顶部常量区(scaffold.py:13 附近)新增
GENRE_DIR = "skills/题材"  # 题材库目录(相对项目根)

# 别名归一:键=别名,值=正式题材文件名(不含 .md)。从 README 别名表来。
GENRE_ALIASES = {
    "玄幻": "修仙", "修真": "修仙", "玄幻修仙": "修仙",
    "都市修真": "都市异能",
    "游戏电竞": "电竞", "电竞文": "电竞",
    "直播": "直播文", "主播": "直播文", "直播带货": "直播文",
    "克系": "克苏鲁", "克系悬疑": "克苏鲁",
}

def _resolve_genre(genre: str | None) -> str | None:
    """归一题材名;命中不到模板就返回 None(永不报错,守离线铁律)。"""
    if not genre:
        return None
    name = GENRE_ALIASES.get(genre.strip(), genre.strip())
    if (TEMPLATES_DIR / GENRE_DIR / f"{name}.md").exists():
        return name
    return None


def init(name: str, parent: Path | None = None, genre: str | None = None) -> Path:
    target = (parent or Path.cwd()) / name
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"目录 {target} 已存在且非空,换个名字或先清空。")

    # 关键改动:全拷时排除整个题材目录(题材按需单拷,不一把铺 37 份)
    def _ignore(dir_path, names):
        if Path(dir_path).resolve() == (TEMPLATES_DIR / "skills").resolve():
            return {"题材"} & set(names)
        return set()

    shutil.copytree(TEMPLATES_DIR, target, dirs_exist_ok=True, ignore=_ignore)

    # 题材命中 → 只拷选中那一份(复合题材可循环拷多份,这里先单份)
    chosen = _resolve_genre(genre)
    if chosen:
        dst_dir = target / GENRE_DIR
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATES_DIR / GENRE_DIR / f"{chosen}.md", dst_dir / f"{chosen}.md")

    # ↓ 以下不变(loom.toml 填名 / 写作指纹中性默认 / 正文.原稿)
    toml = target / "loom.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("__TITLE__", name), encoding="utf-8")
    (target / "外置大脑" / "写作指纹.md").write_text(neutral_default(), encoding="utf-8")
    (target / "正文" / ".原稿").mkdir(parents=True, exist_ok=True)
    gitkeep = target / "正文" / ".gitkeep"
    if gitkeep.exists():
        gitkeep.unlink()
    return target
```

注:genre=None 时 _ignore 仍排除 题材/,项目里就没有 skills/题材/ 目录,行为与今天一致(只是不再误拷 37 份)。调用方(CLI/WebUI 的 init 入口)需把用户选的题材透传给 init 的 genre 形参——这是唯一的上游改动点。

## 设定师.md reads: 改动(设定师.md:3-6)
在 reads: 列表末尾追加一行(占位字面量,文件存在则读,不存在则 Agent 跳过):
    - skills/题材/<题材>.md

## 验收标准

- [ ] loom/templates/skills/题材/ 下有 37 份题材 .md,文件名与清单一致
- [ ] 每份题材文件 ≤一屏(≤60 行或 ≤2KB),且只含五段:核心爽感/读者期待/必备桥段/常见雷区/金手指匹配
- [ ] 题材文件里不含任何 webnovel-writer 残留:无 Pack 约束包、无任务生成器 Prompt、无 <entity> XML、无 hook_config/阈值/债务倍率等打分参数
- [ ] 系统流.md 与 都市异能.md 两份成品按 distilledContent 落盘,内容可直接用
- [ ] skills/题材/README.md 含别名映射表 + 复合题材 7:3 说明
- [ ] scaffold.init() 签名新增 genre 参数;不传 genre 时行为与改动前一致(回归通过),且项目里不再铺 37 份题材文件
- [ ] 传 genre='系统流' init 后,项目里只出现 skills/题材/系统流.md 一份题材文件,无其他题材
- [ ] 传别名(如 genre='玄幻')能归一到 修仙.md;传不存在的题材名不报错、当作没选
- [ ] 设定师.md 的 reads: 含 skills/题材/<题材>.md 占位行;写手.md/润色师.md/写作指纹.md 的 reads 不含任何题材路径

## 红线(防变味)

- ⛔ 题材文件(管 what)只能被设定师 reads;写手/润色师/写作指纹绝不 reads 题材,否则污染'像你'(红线①)
- ⛔ 金手指/桥段/爽点这类剧情套路只写进题材库与世界观链路,物理上不进写作指纹,且 AI 用了题材后不得回流写作指纹(红线②)
- ⛔ 绝不引入 webnovel-writer 的打分参数/route seed/CSV/taxonomy 这类重基础设施(红线③)——题材文件是纯人话 Markdown,可手改、file-as-truth
- ⛔ init 不得因题材缺失/拼错而失败:归一不中就当没选,守 scaffold '永不联网永不因缺失失败'的离线铁律
- ⛔ 保持极简:不为题材新建数据库/索引/解析层,只用 copytree 的 ignore + 单文件 copy;题材是可选增益,默认不选时零行为变化

