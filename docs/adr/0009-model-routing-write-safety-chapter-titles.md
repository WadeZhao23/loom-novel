# 多供应商模型路由 + 模型输出写盘安全闸 + 每章标题

起因是一个用户实报的**数据丢失**:他把顶栏模型从 `deepseek-chat` 改成 `v4-flash`(DeepSeek V4 的正式 API 名其实是 `deepseek-v4-flash`,裸名不被识别)→ DeepSeek 对不认识的模型返回 **200 空响应**(不报错)→ 后端把空串往下传 → `learn` **零校验**地把空串覆盖写进写作指纹 → 他一路 learn 攒下的「你」被擦平。三个环节没有任何一道闸。本 ADR 记三件相关的事。

## 一、写盘安全闸:模型输出绝不静默覆盖用户已攒下的数据

新增 `guard.py`:一切「模型输出 → 覆盖用户文件」的写盘点(写作指纹 learn/seed、正文终稿、流水线每棒产物、起草/补设定/写后摘要)落盘前过 `validate_output`(非空 + 最小实字 + 必需结构标记)。不合格就**保留旧文件、抛友好错误**(`model_output_invalid`),把「静默毁数据」变成「明确报错、原样保护」。后端层另加一道:OpenAI 兼容后端正常返回但**内容为空**时直接 `raise`(`deepseek_empty_response` / `model_empty_response`),不再 `(... or "").strip()` 成空串。**职责切分**:后端只挡「完全空」(len==0);太短/缺结构交给 guard 的 `min_chars`——正常输出永远过得了闸。

**learn 的两层闸,刻意区分硬/软**(守 [ADR-0001](0001-living-writing-fingerprint.md)「不自动给指纹打分、把决定权还给人 + 可撤销」):
- **硬闸(拦)**:空 / 过短 / 丢光小节结构 → 保留旧指纹、绝不写。这不是「打分」,是「这压根不是一份指纹」,属保护数据。
- **软闸(放行 + 提示)**:新指纹合法、但**明显变短**(实字 < 旧的 60%)或 **anchor 留存率 < 80%** → **仍写入**,只发一条「疑似把你的嗓音磨短了,可一键撤销」的提示。绝不硬拦——硬拦等于「机器替你判定 learn 合不合格」,与 ADR-0001 刻意不做自动打分、靠 `.指纹历史` 备份 + `revert_learn` 让人兜的纪律相悖。阈值取 60/80 作起点、留待真稿微调。

附赠类(enrich/recap)模型空响应一律**干净跳过**、绝不阻断 learn(它们本就在 learn 内 try/except);draft 逐段非空才写、缺段跳过(不强求三段齐全)。

## 二、多供应商模型路由:别再把模型名写死成会过时的白名单

根因之一是「模型框是自由文本 + base_url 写死、且无校验」。但**直接的教训是模型名会变**(DeepSeek 一改名,旧默认 `deepseek-chat` 就成了 2026-07-24 即停用的遗留名)。所以方案不是「换一份新白名单」,而是**不依赖固定白名单**:

- `backends.py` 立 `PROVIDERS` 注册表作**路由唯一真相**(前端下拉 / 后端构造 / 模型校验全从它派生)。四个一等公民:`deepseek`(锁死 base_url)、`claude`、`codex`、新增 `openai_compat`(**自填 base_url** 的通用口子,接智谱GLM/Moonshot/Qwen/硅基流动等)。
- `DeepSeekBackend` 退化为通用 `OpenAICompatBackend` 的一个预设(base_url 锁死 api.deepseek.com),DeepSeek/openai_compat 共用同一套流式/错误/空响应逻辑。
- 模型框改成**可编辑下拉(datalist:预设建议 + 手填)** + 一个**「拉取可用模型」**按钮:OpenAI 兼容接口实时打 `GET /models` 列出**当下真实可用**的模型,名字怎么变都不过时(`list_models`,只读、不耗 token)。
- 保存后端时 `validate_model` 做**软提示不阻断**:把 `v4-flash` 填进 DeepSeek 会提示「正式名是 deepseek-v4-flash,或切到 OpenAI 兼容」——正中用户那次的错。
- `config` 加 `base_url`(仅 openai_compat 写进 loom.toml);两把 key 各占 `.env` 一行(`DEEPSEEK_API_KEY` / `LOOM_OPENAI_COMPAT_KEY`)互不覆盖。默认模型从 `deepseek-chat` 升到 `deepseek-v4-flash`。

**保留三个一等公民的既定决策不变**(见记忆「自带 key 决策」):DeepSeek 自带 key、Claude/Codex 复用客户端登录免 key;openai_compat 是「自带 key 的第三方」这一类的通用承载,不自建代理、不卖订阅。

## 三、每章标题:正文首行 `# 标题` 作单一真相

- write 流水线终稿后**自动起一个标题**(附赠动作:失败/空静默回退无标题,绝不阻断出稿),落进正文**首行 `# 标题`**;侧栏解析显示,老章/无 H1 回退「第N章」。标题**只存名字、不含「第N章」**——章号由文件名带,重编号搬文件即可,标题零改动。
- **命门:标题绝不能被 learn 当文风学**。做法是「标题进正文文件、且 `.原稿`快照/`ledger` 都同口径带上它」(保 `chapter_drifted`、局部重写的外科式快照同步口径一致,不会因「正文有标题、快照没标题」恒判手改);**只在量「人手改了多少正文」的三处**——learn 的 diff、`ledger.chapter_drifted`、侧栏/CLI「改过」徽标——先 `strip_title` 再比。于是**只改标题**既不触发 drifted 重写闸、也不进写作指纹。
- 重编号(删/插/移)无需为标题加任何逻辑(标题随 `第N章.md` 整体 `os.replace` 走)。

## 与既有不变量的兼容

- **向后兼容**:老 `loom.toml` 没 `base_url` → `load_config` 兜底空串,无迁移;老正文没 H1 → `strip_title` 原样返回,`ledger` 旧 `snapshot_sha` 与新计算一致,**不给老章凭空补标题**;老 `.env` 只有 DeepSeek key 一切照旧。
- **后端协议不变**:仍只用 `backend.complete`;新增的 openai_compat 走同一协议。
- **ADR 红线全守**:learn 仍只从手改 diff 学、绝不回写 AI 输出;指纹累积不推倒;章节管理不自动改卡章纲;关卡不打分不硬阻断。

## Considered Options(选摘)

- **指纹写盘换一份更严的硬质量闸**——否决:会误杀合法的近义合并/精简,且等于给指纹自动打分,违 ADR-0001。选「硬闸只挡空/残废 + 软闸提示可撤销」。
- **第三方供应商做「选厂商自动填 base_url」的预设子表**——暂缓:先上「单层 datalist + 手填 base_url + 错误文案给各家地址范例 + 拉取可用模型」,把「能接第三方」跑通,避免一上来把第三方半一等公民化。
- **标题单独存 state.json / 独立文件**——否决:多一套要跟章号同步搬的真相,易留孤儿;正文首行 H1 最自然、导出自带、版本历史一体。
