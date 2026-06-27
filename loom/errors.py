"""错误目录:把工程/环境类异常映射成 {标题/原因/影响/下一步} 四段友好文本。

只处理 key/依赖/命令/超时/项目根/文件缺失这类工程错误,绝不碰"怎么写小说"。
纯数据 + 一个 render 函数,不 import 任何 loom 模块、不读写文件、不联网。
backends/config/agents 单向 import 它,无循环依赖。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorError:
    title: str        # 一句话说清"出了什么事"
    reason: str       # 为什么会这样
    impact: str       # 对你写书的影响
    next_action: str  # 你现在该做的一步(可执行)


author_errors: dict[str, AuthorError] = {
    "deepseek_key_missing": AuthorError(
        title="还没填 DeepSeek 的 API key",
        reason="Loom 默认用 DeepSeek 写作,但没在项目根的 .env 里读到 DEEPSEEK_API_KEY。",
        impact="设定师/大纲师/写手等都需要它,现在一步也跑不了。",
        next_action="在项目根新建或打开 .env,加一行 DEEPSEEK_API_KEY=sk-你的key(key 在 https://platform.deepseek.com 申请),保存后重试。",
    ),
    "openai_not_installed": AuthorError(
        title="缺少 openai 这个依赖包",
        reason="DeepSeek 走 OpenAI 兼容接口,需要 openai 库,但当前 Python 环境里没装。",
        impact="DeepSeek 后端无法初始化,写作流水线起不来。",
        next_action="在 Loom 的环境里跑 `pip install openai`(或重装 Loom 依赖)后重试。",
    ),
    "deepseek_auth_failed": AuthorError(
        title="DeepSeek 的 API key 没通过验证",
        reason="DeepSeek 拒绝了这个 key(填错、复制时多了空格、或 key 已被删/停用)。",
        impact="这一步没产出,你的外置大脑和已写章节没受影响。",
        next_action="去 platform.deepseek.com 确认 key 还在、复制完整(以 sk- 开头),在顶栏重新填一遍 API Key 再写。",
    ),
    "deepseek_insufficient_balance": AuthorError(
        title="DeepSeek 账户余额不足",
        reason="key 没问题,但账户里没钱了——DeepSeek 按字数计费,余额用完就调不动。",
        impact="这一步没产出,已写的章节和外置大脑都安全。",
        next_action="去 platform.deepseek.com 充值(几块钱能写很久),充好后重试;或顶栏切到 Claude 后端先继续。",
    ),
    "deepseek_rate_limited": AuthorError(
        title="DeepSeek 这会儿被限流了",
        reason="短时间请求太多(或平台高峰),DeepSeek 暂时挡了一下。",
        impact="只是这一下没成,没扣坏任何东西。",
        next_action="等十几秒再点一次;若总是这样,把章节字数调小一点,或错峰再写。",
    ),
    "deepseek_call_failed": AuthorError(
        title="调用 DeepSeek 没成功",
        reason="网络不通、平台抽风或一个还没归类的接口错误。",
        impact="这一步没产出,你的稿子没受影响。",
        next_action="检查网络后重试;若反复失败,顶栏切到 Claude 后端,或看下面的细节反馈。",
    ),
    "claude_not_found": AuthorError(
        title="找不到 claude 命令",
        reason="loom.toml 里 provider 设成了 claude,但系统 PATH 里没有 `claude`。",
        impact="选了 Claude 后端却调不起来,写作无法进行。",
        next_action="装好 Claude Code 并确认终端能跑 `claude --version`;或把 loom.toml 的 provider 改回 deepseek。",
    ),
    "claude_timeout": AuthorError(
        title="claude 这次跑超时了",
        reason="`claude -p` 在限定时间内没返回(提示词太长或本机太慢都可能)。",
        impact="这一章/这一步没产出,但你的外置大脑和已写章节没受影响。",
        next_action="稍后重试;若反复超时,把章节字数调小一点,或在 loom.toml 把 provider 换成 deepseek。",
    ),
    "codex_not_found": AuthorError(
        title="找不到 codex 命令",
        reason="loom.toml 里 provider 设成了 codex,但系统 PATH 里没有 `codex`(没装,或装了但没登录)。",
        impact="选了 Codex 后端却调不起来,写作无法进行。",
        next_action="装好 Codex CLI(`npm i -g @openai/codex`)、跑一次 `codex login` 用 ChatGPT 订阅登录,确认 `codex --version` 能跑;或把 provider 改回 deepseek/claude。Codex 复用它自己的登录,不用在 Loom 填 key。",
    ),
    "codex_timeout": AuthorError(
        title="codex 这次跑超时了",
        reason="`codex exec` 在限定时间内没返回(提示词太长或本机太慢都可能)。",
        impact="这一章/这一步没产出,但你的外置大脑和已写章节没受影响。",
        next_action="稍后重试;若反复超时,把章节字数调小一点,或在 loom.toml 把 provider 换成 deepseek。可用 LOOM_CODEX_TIMEOUT 放宽超时。",
    ),
    "codex_call_failed": AuthorError(
        title="调用 codex 没成功",
        reason="codex 返回了非零(可能没登录、模型名不对、网络不通,或一个还没归类的 CLI 错误)。",
        impact="这一步没产出,你的稿子没受影响。",
        next_action="先在终端跑一次 `codex exec \"你好\"` 确认 codex 本身能用、已 `codex login`;若 model 填了 codex 不认的名字,清空模型框让它用默认。细节见下方反馈。",
    ),
    "project_root_not_found": AuthorError(
        title="这里不是一个 Loom 项目",
        reason="从当前目录一路向上都没找到 loom.toml,无法确定要操作哪本书。",
        impact="seed / write / learn 都需要项目根,现在无从下手。",
        next_action="先 `loom init <书名>` 建项目,再 `cd` 进去;或 cd 到已有的 Loom 项目目录后重试。",
    ),
    "agent_prompt_missing": AuthorError(
        title="缺少某个 agent 的提示词文件",
        reason="流水线要按角色加载 agents/<角色>.md,但这个文件不在(项目骨架可能被误删/移动)。",
        impact="对应工序无法运行,整章写作中断。",
        next_action="确认 agents/ 目录下五个角色文件齐全(设定师/大纲师/写手/编辑/润色师);缺了就从模板恢复,或重新 init 一个项目对照补回。",
    ),
    # ---- 模型输出 / 路由相关(写盘安全闸 + 多供应商路由)----
    "model_output_invalid": AuthorError(
        title="模型这次没产出有效结果,已为你刹住",
        reason="后端返回了空/过短/结构不完整的内容(多半是模型名填错、或这个模型答非所问)。",
        impact="你原来的写作指纹 / 正文【一个字都没动】——Loom 宁可不写,也不拿一坨空的覆盖你攒下的东西。",
        next_action="把顶栏模型换回该供应商的正常模型(DeepSeek 选 deepseek-v4-flash)再试一次;或点「拉取可用模型」看看这家到底有哪些模型可选。",
    ),
    "deepseek_empty_response": AuthorError(
        title="DeepSeek 返回了空内容",
        reason="DeepSeek V4(v4-flash/v4-pro)是【思考型】模型:它先思考、再写正文,思考也占 token 预算。这一步的预算多半被思考占满了,正文就空着回来——(少数情况才是模型名填错,正式名是 deepseek-v4-flash / deepseek-v4-pro)。",
        impact="这一步没产出,你的指纹和已写章节都【原样保住了】。",
        next_action="把「章节字数」调大一点(给思考留余量)再试,通常就好;仍不行就确认顶栏模型名是 deepseek-v4-flash 或 deepseek-v4-pro。想用别家模型,把供应商切到「OpenAI 兼容(自定义)」再填它的 base_url。",
    ),
    "model_empty_response": AuthorError(
        title="这个模型返回了空内容",
        reason="OpenAI 兼容接口收到了 200 但内容是空的,常见于模型名不对、或该模型在这个 base_url 下不可用。",
        impact="这一步没产出,你的稿子和指纹没受影响。",
        next_action="点「拉取可用模型」确认这家供应商真有你填的这个模型名;或检查 base_url 是否填对(各家地址不同)。",
    ),
    "backend_empty_response": AuthorError(
        title="后端命令返回了空内容",
        reason="claude / codex 子进程跑完了却没吐出正文(可能模型名不对、或这次被客户端拦下)。",
        impact="这一步没产出,你的稿子没受影响。",
        next_action="清空顶栏模型框让它用默认模型再试;或在终端单独跑一次该命令确认它本身能出文字。",
    ),
    "model_call_failed": AuthorError(
        title="调用这个模型没成功",
        reason="网络不通、base_url/key 不对,或一个还没归类的接口错误。",
        impact="这一步没产出,你的稿子没受影响。",
        next_action="检查 base_url 与 API Key 是否填对、网络是否可达;或先切回 DeepSeek 继续写。细节见下方反馈。",
    ),
    "openai_compat_base_url_missing": AuthorError(
        title="还没填这个供应商的 base_url",
        reason="选了「OpenAI 兼容(自定义)」供应商,但没填它的接口地址(base_url)。",
        impact="不知道该把请求发到哪,后端起不来。",
        next_action="在顶栏填该供应商的 base_url(智谱GLM:https://open.bigmodel.cn/api/paas/v4 · Moonshot:https://api.moonshot.cn/v1 · 通义Qwen:https://dashscope.aliyuncs.com/compatible-mode/v1 · 硅基流动:https://api.siliconflow.cn/v1),再填模型名与 key。",
    ),
    "openai_compat_key_missing": AuthorError(
        title="还没填这个供应商的 API Key",
        reason="选了「OpenAI 兼容(自定义)」供应商,但没在项目 .env 里读到它的 key(LOOM_OPENAI_COMPAT_KEY)。",
        impact="这家供应商要鉴权,没 key 调不动。",
        next_action="在顶栏 API Key 框填这家供应商给你的 key,点「保存后端」(它会写进项目 .env,与 DeepSeek 的 key 各占一行,互不覆盖)。",
    ),
    "model_name_missing": AuthorError(
        title="还没填模型名",
        reason="OpenAI 兼容供应商必须明确指定一个模型名,但模型框是空的。",
        impact="不知道要调哪个模型,后端起不来。",
        next_action="在顶栏模型框填这家供应商的一个模型名;不确定有哪些,点「拉取可用模型」让它列出来。",
    ),
    "fingerprint_inherit_invalid": AuthorError(
        title="要继承的指纹文件不像一份有效指纹",
        reason="选来继承的那份写作指纹文件是空的、或读不出小节结构(可能选错了文件)。",
        impact="没有继承、你当前的指纹原样保留,没被覆盖。",
        next_action="确认选的是另一本书 外置大脑/写作指纹.md(里面应有「## 句式偏好」这类小节);选对了再继承。",
    ),
}


FALLBACK = AuthorError(
    title="遇到一个还没登记的问题",
    reason="这是 Loom 错误目录里还没归类的情况。",
    impact="当前这一步没完成。",
    next_action="重试一次;若仍失败,把下面的细节连同你刚才点的操作一起反馈。",
)


def render(code_or_error, *, detail: str = "") -> str:
    e = code_or_error if isinstance(code_or_error, AuthorError) else author_errors.get(code_or_error, FALLBACK)
    lines = [e.title, "", f"· 原因:{e.reason}", f"· 影响:{e.impact}", f"· 下一步:{e.next_action}"]
    if detail:
        lines += ["", f"(细节:{detail})"]
    return "\n".join(lines)
