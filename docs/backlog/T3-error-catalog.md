# T3-error-catalog · 错误目录 errors.py:把后端/CLI/Server 的"友好一行"升级成结构化四段(标题/原因/影响/下一步)
- **类型**: code　**工作量**: small　**批次**: 批次1 · 零风险即做(纯内容/隔离小代码)
- **依赖**: 无
- **涉及文件**:
  - `loom/errors.py`
  - `loom/backends.py`
  - `loom/config.py`
  - `loom/agents.py`
  - `loom/cli.py`

## 问题(Loom 现状)

Loom 现在的错误提示是散落在各处、长短不一的"友好一行字符串",同一类错误在 CLI 和 WebUI 两条路径上质量不一致,且没有统一的"原因/影响/下一步"结构,新手撞墙时不知道下一步该干嘛。具体现状:
- backends.py:32-36 DEEPSEEK_API_KEY 缺失:有较完整的多行提示(算目前最好的一个),但格式是手写多行字符串,无法复用。
- backends.py:38 `from openai import OpenAI`:无 try,没装 openai 时直接抛 ModuleNotFoundError 裸栈,用户看到的是 traceback 而不是"pip install openai"。这是当前最严重的裸异常缺口。
- backends.py:64-67 claude 命令缺失:一行提示,没说怎么装。
- backends.py:82-84 claude 超时:`subprocess.run(timeout=240)` 的 TimeoutExpired 被 `except Exception` 笼统吞成"调用 claude 失败:{e}",超时和网络错混为一谈,没有"换 deepseek 或减小章节字数"的下一步。
- config.py:26-28 找不到 loom.toml:一行提示。
- agents.py:69-70 缺 agent 提示词:一行提示("骨架是不是被改坏了?"),没说怎么修。
这些提示在 cli.py:_die(25-27) 里被打成单行红字,在 server.py 里被打成 `{"error": str(e)}` JSON——两边都只拿到一个扁平字符串,无法分级展示。缺一个统一的错误目录把异常映射成 {title/reason/impact/next_action} 四段。

## 从 webnovel-writer 借什么 / 丢什么

借鉴源:/tmp/webnovel-writer/webnovel-writer/references/author_error_catalog.json(已真实读取)。
要借的【精华】——它的"作者友好报告"思想:把每个错误映射成固定四段结构 title(标题)/reason(原因)/impact(影响)/next_action(下一步),外加一个 fallback 兜底条目处理未登记错误。这套"四段 + 兜底"是直接可用的心智模型。
明确丢弃(都属于重基础设施/解析层/与 Loom 无关的领域概念):
- `schema_version: "webnovel-author-error-catalog/v1"`——红线③禁的版本号 schema 那套,丢。
- `match: {codes/contains}` 字符串模式匹配引擎——Loom 用 Python 异常类型直接 dispatch,不做字符串模糊匹配,丢这整个解析层。
- `severity`(must_handle/needs_confirmation/auto_handled)+ `auto_handle` 自动处理标志——Loom 没有自动修复机制(反过度工程),所有错误都是"告诉用户怎么办",丢。
- `command: "/webnovel-doctor"`——Loom 没有 doctor 命令也不是 Claude-Code skill,丢。
- 所有具体错误条目(mainline_ready/write-gate/projection/rag degraded 等)——全是 webnovel-writer 的投影链/RAG/向量库领域概念(正是红线③禁止引入的基础设施),与 Loom 的 6 个真实错误点零重叠,全部丢弃,只保留"四段结构 + fallback"这个空壳思想。

## Loom 落地设计

新增 loom/errors.py,提供:
1. `@dataclass(frozen=True) AuthorError`:字段 title/reason/impact/next_action(纯数据,无 severity/command/schema_version)。
2. `author_errors: dict[str, AuthorError]`:键是 Loom 内部稳定错误码(字符串常量,如 "deepseek_key_missing"),值是四段成品。覆盖 6 个码:deepseek_key_missing / openai_not_installed / claude_not_found / claude_timeout / project_root_not_found / agent_prompt_missing。
3. `FALLBACK: AuthorError`:兜底条目,用于未登记错误。
4. `render(code_or_error, *, detail="") -> str`:渲染成统一多行纯文本(CLI / JSON 都能用),detail 用于追加原始异常细节(如超时秒数、缺失文件路径)。
5. `LoomBackendError` 增加可选 `code` 属性(向后兼容:不传 code 时退化成今天的纯字符串行为),让 errors.py 与 backends.py 解耦——backends 抛错时带上 code,渲染交给上层。

接入点(精确):
- backends.py:16 `class LoomBackendError(RuntimeError)`:改造为 `__init__(self, message, *, code=None)`,存 self.code。
- backends.py:32-36(DeepSeek key 缺失):改抛 `LoomBackendError(render("deepseek_key_missing"), code="deepseek_key_missing")`。
- backends.py:38(`from openai import OpenAI`):包 try/except ModuleNotFoundError,抛 code="openai_not_installed"。
- backends.py:64-67(claude 缺失):code="claude_not_found"。
- backends.py:82-84(claude 调用):把 `except Exception` 拆出 `except subprocess.TimeoutExpired` → code="claude_timeout"(detail 带 timeout=240s),其余 Exception 保持现状友好行。
- config.py:26-28(find_project_root):FileNotFoundError 的消息体改用 `render("project_root_not_found")`(config.py 已无 backends 依赖,直接 import errors,无环)。
- agents.py:69-70(load_agent 缺提示词):FileNotFoundError 消息改用 `render("agent_prompt_missing", detail=str(path))`。
- cli.py:_die(25-27):无需改签名(已接受纯字符串 msg),错误文本已在抛出点渲染好,_die 原样打印多行即可。可选:把 `console.print(Panel(...))` 包一层让四段更醒目,但非必须。
- server.py 各 `JSONResponse({"error": str(e)}, ...)`(79/87/91/110/157/172/192)与 write worker 的 `{"type":"error","message":str(e)}`(202/204):str(e) 现在天然就是渲染好的多段文本,无需逐处改;前端把 \n 正常换行展示即可。

数据流:异常在源头(backends/config/agents)用 render() 把 code 渲染成四段文本塞进 exception message → 上层(cli._die / server JSONResponse / write worker)拿到的 str(e) 已是成品,零额外逻辑。errors.py 不 import 任何 loom 模块(backends 反向 import errors),无循环依赖。

## 代码草图

# loom/errors.py（新增，纯数据 + 渲染，不 import 任何 loom 模块）
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class AuthorError:
    title: str        # 一句话说清"出了什么事"
    reason: str       # 为什么会这样
    impact: str       # 对你写书的影响
    next_action: str  # 你现在该做的一步（可执行）

author_errors: dict[str, AuthorError] = {
    "deepseek_key_missing": AuthorError(
        title="还没填 DeepSeek 的 API key",
        reason="Loom 默认用 DeepSeek 写作，但没在项目根的 .env 里读到 DEEPSEEK_API_KEY。",
        impact="设定师/大纲师/写手等都需要它，现在一步也跑不了。",
        next_action="在项目根新建或打开 .env，加一行 DEEPSEEK_API_KEY=sk-你的key（key 在 https://platform.deepseek.com 申请），保存后重试。",
    ),
    "openai_not_installed": AuthorError(
        title="缺少 openai 这个依赖包",
        reason="DeepSeek 走 OpenAI 兼容接口，需要 openai 库，但当前 Python 环境里没装。",
        impact="DeepSeek 后端无法初始化，写作流水线起不来。",
        next_action="在 Loom 的环境里跑 `pip install openai`（或重装 Loom 依赖）后重试。",
    ),
    "claude_not_found": AuthorError(
        title="找不到 claude 命令",
        reason="loom.toml 里 provider 设成了 claude，但系统 PATH 里没有 `claude`。",
        impact="选了 Claude 后端却调不起来，写作无法进行。",
        next_action="装好 Claude Code 并确认终端能跑 `claude --version`；或把 loom.toml 的 provider 改回 deepseek。",
    ),
    "claude_timeout": AuthorError(
        title="claude 这次跑超时了",
        reason="`claude -p` 在限定时间内没返回（提示词太长或本机太慢都可能）。",
        impact="这一章/这一步没产出，但你的外置大脑和已写章节没受影响。",
        next_action="稍后重试；若反复超时，把章节字数调小一点，或在 loom.toml 把 provider 换成 deepseek。",
    ),
    "project_root_not_found": AuthorError(
        title="这里不是一个 Loom 项目",
        reason="从当前目录一路向上都没找到 loom.toml，无法确定要操作哪本书。",
        impact="seed / write / learn 都需要项目根，现在无从下手。",
        next_action="先 `loom init <书名>` 建项目，再 `cd` 进去；或 cd 到已有的 Loom 项目目录后重试。",
    ),
    "agent_prompt_missing": AuthorError(
        title="缺少某个 agent 的提示词文件",
        reason="流水线要按角色加载 agents/<角色>.md，但这个文件不在（项目骨架可能被误删/移动）。",
        impact="对应工序无法运行，整章写作中断。",
        next_action="确认 agents/ 目录下五个角色文件齐全（设定师/大纲师/写手/编辑/润色师）；缺了就从模板恢复，或重新 init 一个项目对照补回。",
    ),
}

FALLBACK = AuthorError(
    title="遇到一个还没登记的问题",
    reason="这是 Loom 错误目录里还没归类的情况。",
    impact="当前这一步没完成。",
    next_action="重试一次；若仍失败，把下面的细节连同你刚才点的操作一起反馈。",
)

def render(code_or_error, *, detail: str = "") -> str:
    e = code_or_error if isinstance(code_or_error, AuthorError) else author_errors.get(code_or_error, FALLBACK)
    lines = [e.title, "", f"· 原因：{e.reason}", f"· 影响：{e.impact}", f"· 下一步：{e.next_action}"]
    if detail:
        lines += ["", f"（细节：{detail}）"]
    return "\n".join(lines)

# ---- loom/backends.py 接入草图 ----
# class LoomBackendError(RuntimeError):
#     def __init__(self, message: str, *, code: str | None = None) -> None:
#         super().__init__(message); self.code = code
#
# from .errors import render
# # key 缺失：
# if not api_key:
#     raise LoomBackendError(render("deepseek_key_missing"), code="deepseek_key_missing")
# # openai 未装：
# try:
#     from openai import OpenAI
# except ModuleNotFoundError as e:
#     raise LoomBackendError(render("openai_not_installed"), code="openai_not_installed") from e
# # claude 缺失：
# if shutil.which("claude") is None:
#     raise LoomBackendError(render("claude_not_found"), code="claude_not_found")
# # claude 超时（拆出 TimeoutExpired）：
# try:
#     out = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
# except subprocess.TimeoutExpired as e:
#     raise LoomBackendError(render("claude_timeout", detail="timeout=240s"), code="claude_timeout") from e
# except Exception as e:
#     raise LoomBackendError(f"调用 claude 失败：{e}") from e
#
# ---- loom/config.py 接入草图 ----
# from .errors import render
# raise FileNotFoundError(render("project_root_not_found"))
#
# ---- loom/agents.py 接入草图 ----
# from .errors import render
# if not path.exists():
#     raise FileNotFoundError(render("agent_prompt_missing", detail=str(path)))

## 验收标准

- [ ] loom/errors.py 存在，含 AuthorError dataclass、author_errors dict(6 个码全覆盖)、FALLBACK、render() 五者
- [ ] render() 对已知码输出含 标题/原因/影响/下一步 四段；对未知码返回 FALLBACK 渲染
- [ ] render(code, detail=...) 能把原始细节(超时秒数/缺失路径)附在末尾
- [ ] 未装 openai 时跑 DeepSeek 后端不再抛 ModuleNotFoundError 裸栈，而是 render('openai_not_installed') 的四段文本
- [ ] claude 超时被 subprocess.TimeoutExpired 单独捕获并映射成 claude_timeout（不再与网络错混为一行）
- [ ] DEEPSEEK_API_KEY/claude 缺失/项目根找不到/agent 提示词缺失 四处的提示文本均来自 errors.py，源头不再手写多行字符串
- [ ] LoomBackendError 带可选 code 属性且不破坏旧调用(不传 code 时行为不变)
- [ ] cli.py 的 _die 能完整打印多行四段文本（不截断成一行）
- [ ] server.py 各 JSONResponse error 字段与 write worker error message 直接复用 str(e)，前端按 \n 换行展示，无需逐处改 dispatch
- [ ] errors.py 不 import 任何 loom 模块；backends/config/agents → errors 单向依赖，无循环 import

## 红线(防变味)

- ⛔ 只处理工程/环境类错误（key/依赖/命令/超时/项目根/文件缺失），绝不碰任何题材/金手指/剧情套路——errors.py 里不准出现一句关于'怎么写小说'的话，守红线①（voice 与 what 隔离）
- ⛔ 不引入 webnovel-writer 的 match 模式匹配引擎、severity 分级、auto_handle 自动修复、command/doctor、schema_version——只取'四段+fallback'空壳，守红线③（反重基础设施）
- ⛔ dispatch 用 Python 异常类型/显式 code 字符串常量，不做错误消息的字符串模糊匹配（那是被丢弃的解析层）
- ⛔ errors.py 是纯数据 + 一个 render 函数，不 import loom 任何模块、不读写文件、不联网，保持极简与本地
- ⛔ 不改变现有控制流：仍是'抛 LoomBackendError/FileNotFoundError/ValueError → 上层 _die / JSONResponse 兜住'，只替换消息内容，不新增中间层或注册表机制
- ⛔ 不触碰写作指纹/外置大脑任何文件，本工单与'像你'链路零交集

