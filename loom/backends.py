"""可插拔后端:一个 complete(system, user) -> str 的协议 + 实现 + 供应商路由表。

两类后端:
- OpenAI 兼容(HTTP):DeepSeek 是锁死 base_url 的预设;openai_compat 是用户自填 base_url 的通用口子
  (接智谱GLM / Moonshot / 通义Qwen / 硅基流动 等),两者共用同一个 OpenAICompatBackend。
- CLI:Claude 走 `claude -p`、Codex 走 `codex exec`,shell 到本机客户端、复用其登录态,Loom 不碰 key。

路由唯一真相是 PROVIDERS:前端下拉、后端构造、模型校验全从它派生——避免「模型名写死成白名单、
厂商一改名就过时再炸一遍」(用户实报:DeepSeek 改名 v4-flash/v4-pro 把旧默认 deepseek-chat 顶没了)。

所有 complete 在【正常返回】也会校验非空:空响应一律 raise(带 code),绝不把空串往下传——
这是用户实报「换模型 → learn 学到空 → 指纹被擦」链条上后端这一环的闸(写盘那一环在 guard.py)。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Protocol

from .config import Config
from .errors import render

# 流式回调:每收到一小段生成文本就调一次(让前端"看着它一句句写出来")。
OnChunk = Callable[[str], None]


# ----------------------------- 供应商路由表(唯一真相) -----------------------------
# kind: "openai"=OpenAI 兼容 HTTP;"cli"=shell 到本机客户端。
# models 只是【预设建议】,前端是可编辑下拉 + 「拉取可用模型」实时拉真实列表,名字怎么变都不过时。
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "label": "DeepSeek", "kind": "openai",
        "base_url": "https://api.deepseek.com", "base_url_locked": True,
        "key_env": "DEEPSEEK_API_KEY", "needs_key": True,
        "default_model": "deepseek-v4-pro",
        # 现役 V4 都是【思考型】模型(deepseek-chat 非思考别名已停用);backend 已为思考预留 token 预算
        # (见 OpenAICompatBackend.complete)。默认 pro(更强);更快更省可选 flash。
        "models": [
            {"id": "deepseek-v4-pro", "label": "V4 Pro · 更强(默认)"},
            {"id": "deepseek-v4-flash", "label": "V4 Flash · 更快·更省"},
        ],
        "can_list_models": True,
    },
    "claude": {
        "label": "Claude Code", "kind": "cli",
        "needs_key": False, "default_model": "sonnet",
        "models": [
            {"id": "sonnet", "label": "Sonnet · 均衡(默认,别名自动跟最新)"},
            {"id": "opus", "label": "Opus · 最强"},
            {"id": "haiku", "label": "Haiku · 最快最省"},
        ],
        "can_list_models": False,
    },
    "codex": {
        "label": "Codex(GPT)", "kind": "cli",
        "needs_key": False, "default_model": "",
        "models": [
            {"id": "", "label": "默认(codex 自己选,推荐)"},
            {"id": "gpt-5.3-codex", "label": "GPT-5.3-Codex · 编码最强"},
            {"id": "gpt-5.5", "label": "GPT-5.5 · 通用最强"},
        ],
        "can_list_models": False,
    },
    "openai_compat": {
        "label": "OpenAI 兼容(自定义)", "kind": "openai",
        "base_url": "", "base_url_locked": False,
        "key_env": "LOOM_OPENAI_COMPAT_KEY", "needs_key": True,
        "default_model": "",
        "models": [],   # 用户自填 / 点「拉取可用模型」实时拉
        "hint": "智谱GLM: https://open.bigmodel.cn/api/paas/v4 · Moonshot: https://api.moonshot.cn/v1 · "
                "通义Qwen: https://dashscope.aliyuncs.com/compatible-mode/v1 · 硅基流动: https://api.siliconflow.cn/v1",
        "can_list_models": True,
    },
}


def provider_catalog() -> list[dict]:
    """给前端的供应商清单(下拉/默认值/预设模型全从这派生)。"""
    out = []
    for pid, p in PROVIDERS.items():
        out.append({
            "id": pid, "label": p["label"], "kind": p["kind"],
            "needs_key": p["needs_key"], "default_model": p["default_model"],
            "base_url": p.get("base_url", ""), "base_url_locked": p.get("base_url_locked", True),
            "models": p.get("models", []), "hint": p.get("hint", ""),
            "can_list_models": p.get("can_list_models", False),
        })
    return out


def validate_model(provider: str, model: str) -> str | None:
    """启发式软校验(不联网):明显填错就返回一句人话提示,否则 None 放行。只警告、绝不阻断保存。"""
    model = (model or "").strip()
    provider = (provider or "").lower()
    if not model or provider not in PROVIDERS:
        return None
    if provider == "deepseek" and "deepseek" not in model.lower():
        return (f"模型名「{model}」不像 DeepSeek 的模型——DeepSeek 现在是 deepseek-v4-flash / deepseek-v4-pro。"
                f"如果你本来想用别家的「{model}」,把上面的供应商切到「OpenAI 兼容(自定义)」再填它的 base_url。")
    return None


class LoomBackendError(RuntimeError):
    """后端层的友好错误(CLI 会把它打成多段提示,而不是抛栈)。

    可选 code 指向 errors.py 的错误目录;不传时退化成普通字符串错误,向后兼容。
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def _deepseek_error(e: Exception) -> LoomBackendError:
    """把 DeepSeek/OpenAI SDK 的异常映射成可操作的友好错误(鉴权/余额/限流/通用)。"""
    msg = str(e)
    status = getattr(e, "status_code", None)
    if status is None:
        status = getattr(getattr(e, "response", None), "status_code", None)
    low = msg.lower()
    if status == 401 or "authentication" in low or "invalid api key" in low:
        code = "deepseek_auth_failed"
    elif status == 402 or "insufficient balance" in low or "余额" in msg:
        code = "deepseek_insufficient_balance"
    elif status == 429 or "rate limit" in low or "too many requests" in low:
        code = "deepseek_rate_limited"
    else:
        return LoomBackendError(render("deepseek_call_failed", detail=msg), code="deepseek_call_failed")
    return LoomBackendError(render(code), code=code)


def _openai_compat_error(e: Exception) -> LoomBackendError:
    """通用 OpenAI 兼容供应商的异常映射(没有 DeepSeek 那么细,够用就好)。"""
    msg = str(e)
    status = getattr(e, "status_code", None)
    if status is None:
        status = getattr(getattr(e, "response", None), "status_code", None)
    low = msg.lower()
    if status == 401 or "authentication" in low or "invalid api key" in low:
        return LoomBackendError(render("openai_compat_key_missing", detail=msg), code="openai_compat_key_missing")
    return LoomBackendError(render("model_call_failed", detail=msg), code="model_call_failed")


class Backend(Protocol):
    def complete(self, system: str, user: str, *, max_chars: int | None = None,
                 on_chunk: OnChunk | None = None) -> str:
        """生成。给了 on_chunk 的后端会边生成边回调(流式);不支持流式的后端忽略它、结尾一次性返回。"""
        ...


def _budget_tokens(provider: str, max_chars: int | None) -> int:
    """max_tokens 预算。中文 ~1.6 token/字 + 余量。

    DeepSeek V4(v4-flash/v4-pro)是【思考型】:reasoning 也吃 max_tokens,小预算步骤(标题/复审)
    易被思考占满 → content 空(deepseek_empty_response 的真因)。给思考留足余量(+4096)+ 底线(6144)、
    封顶 8192(DeepSeek 接受的上限)。其它 OpenAI 兼容供应商维持原样——它们各家模型输出上限不同,
    贸然抬高 max_tokens 可能被拒。"""
    if not max_chars:
        return 8192 if provider == "deepseek" else 2048
    base = int(max_chars * 2.2)
    if provider == "deepseek":
        return min(8192, max(6144, base + 4096))
    return base


class OpenAICompatBackend:
    """OpenAI 兼容 HTTP 后端:DeepSeek(锁死 base_url)和 openai_compat(自填 base_url)共用。"""

    def __init__(self, config: Config, provider: str) -> None:
        spec = PROVIDERS[provider]
        self.provider = provider
        self.model = (config.model or "").strip() or spec["default_model"]
        # base_url:锁死的取注册表,自定义的取 config.base_url
        base_url = spec["base_url"] if spec.get("base_url_locked") else ((config.base_url or "").strip() or spec.get("base_url", ""))
        self._empty_code = "deepseek_empty_response" if provider == "deepseek" else "model_empty_response"
        self._map = _deepseek_error if provider == "deepseek" else _openai_compat_error

        if provider != "deepseek" and not self.model:
            raise LoomBackendError(render("model_name_missing"), code="model_name_missing")
        if not base_url:
            raise LoomBackendError(render("openai_compat_base_url_missing"), code="openai_compat_base_url_missing")
        api_key = os.environ.get(spec["key_env"])
        if not api_key:
            code = "deepseek_key_missing" if provider == "deepseek" else "openai_compat_key_missing"
            raise LoomBackendError(render(code), code=code)
        # 延迟 import,免得没装 openai 时连 --help 都跑不起来
        try:
            from openai import OpenAI
        except ModuleNotFoundError as e:
            raise LoomBackendError(render("openai_not_installed"), code="openai_not_installed") from e
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def _empty(self) -> LoomBackendError:
        return LoomBackendError(render(self._empty_code, detail=f"model={self.model}"), code=self._empty_code)

    def complete(self, system: str, user: str, *, max_chars: int | None = None,
                 on_chunk: OnChunk | None = None) -> str:
        max_tokens = _budget_tokens(self.provider, max_chars)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            if on_chunk is not None:  # 流式:边写边回调
                stream = self._client.chat.completions.create(
                    model=self.model, messages=messages, max_tokens=max_tokens,
                    temperature=0.9, stream=True,
                )
                parts, buf = [], ""
                for ev in stream:
                    delta = (ev.choices[0].delta.content or "") if ev.choices else ""
                    if not delta:
                        continue
                    parts.append(delta)
                    buf += delta
                    if len(buf) >= 8 or buf[-1] in "。\n!?!?…":  # 攒几字/到句末再发,别一 token 一行
                        on_chunk(buf)
                        buf = ""
                if buf:
                    on_chunk(buf)
                text = "".join(parts).strip()
            else:
                resp = self._client.chat.completions.create(
                    model=self.model, messages=messages, max_tokens=max_tokens, temperature=0.9,
                )
                text = (resp.choices[0].message.content or "").strip()
        except Exception as e:  # 网络/限流/鉴权/余额 —— 映射成可操作的友好错误
            raise self._map(e) from e
        if not text:  # 200 空响应(多半模型名不对)→ 报错,绝不把空串往下传去覆盖用户数据
            raise self._empty()
        return text


class ClaudeCodeBackend:
    """接 Claude Code:把 system+user 拼成 prompt 走 `claude -p` headless。"""

    def __init__(self, config: Config) -> None:
        if shutil.which("claude") is None:
            raise LoomBackendError(render("claude_not_found"), code="claude_not_found")
        # 让 loom.toml 的 model 生效;没填/填了别家(deepseek/gpt)默认值时退回 sonnet(写文质量好,禁工具后仍是一次性补全)
        m = (config.model or "").strip()
        bad = (not m) or ("deepseek" in m) or m.startswith("gpt")
        self.model = "sonnet" if bad else m

    # 护栏:逼 `claude -p` 当"纯文本补全",别当 Claude Code agent(去找文件/反问/解释)
    _GUARD = (
        "[严格指令] 你是一个纯文本生成函数,不是助手、不是 agent。只输出要求的成品中文文本本身。"
        "禁止:调用或提及任何工具、查找或读取任何文件、反问、说明你在做什么、"
        "输出「我检查了目录」「请提供」之类的话。你需要的全部材料都在下面,直接用。"
    )

    def complete(self, system: str, user: str, *, max_chars: int | None = None,
                 on_chunk: OnChunk | None = None) -> str:
        # claude 子进程不做 token 级流式(返回即全量);on_chunk 接受但忽略,前端靠 agent_done 展示。
        prompt = f"{self._GUARD}\n\n{system}\n\n---\n\n{user}"
        # 关键:用快模型 + 禁工具,把 `claude -p` 压成一次性文本补全。
        # 否则它会以完整 agent 形态运行(调工具、反复探索),大 prompt 直接跑到超时。
        cmd = ["claude", "-p", prompt, "--model", self.model, "--allowed-tools", ""]
        timeout = int(os.environ.get("LOOM_CLAUDE_TIMEOUT", "600"))  # sonnet 写长章较慢,放宽;可环境覆盖
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise LoomBackendError(render("claude_timeout", detail=f"timeout={timeout}s"), code="claude_timeout") from e
        except Exception as e:
            raise LoomBackendError(f"调用 claude 失败:{e}") from e
        if out.returncode != 0:
            raise LoomBackendError(f"claude 返回非零:{out.stderr.strip()}")
        text = out.stdout.strip()
        if not text:  # 跑完却没吐正文 → 报错,别把空往下传
            raise LoomBackendError(render("backend_empty_response", detail=f"model={self.model}"),
                                   code="backend_empty_response")
        return text


class CodexBackend:
    """接 Codex CLI:把 system+user 拼成 prompt 走 `codex exec` 非交互(headless)。

    复用 codex 客户端自己的登录态(ChatGPT 订阅 / OPENAI_API_KEY),Loom 不碰 key——
    和 Claude 后端同一套思路:shell 到装好的客户端,鉴权交给客户端。
    """

    def __init__(self, config: Config) -> None:
        if shutil.which("codex") is None:
            raise LoomBackendError(render("codex_not_found"), code="codex_not_found")
        # 只在用户显式配了 codex 适用的模型时才传 --model;否则让 codex 用它自己的默认模型
        # (订阅登录下默认模型即可,硬塞一个模型名反而可能"未知模型")。
        m = (config.model or "").strip()
        self.model = m if m and "deepseek" not in m else ""

    # 护栏:逼 `codex exec` 当"纯文本补全",别当 Codex agent(改文件/跑命令/反问)
    _GUARD = (
        "[严格指令] 你是一个纯文本生成函数,不是助手、不是 agent。只输出要求的成品中文文本本身。"
        "禁止:调用或提及任何工具、读写或查找任何文件、执行命令、反问、说明你在做什么、"
        "输出「我检查了目录」「请提供」之类的话。你需要的全部材料都在下面,直接用。"
    )

    def complete(self, system: str, user: str, *, max_chars: int | None = None,
                 on_chunk: OnChunk | None = None) -> str:
        # codex 子进程不做 token 级流式(返回即全量);on_chunk 接受但忽略,前端靠 agent_done 展示。
        prompt = f"{self._GUARD}\n\n{system}\n\n---\n\n{user}"
        timeout = int(os.environ.get("LOOM_CODEX_TIMEOUT", "600"))  # 与 claude 一致放宽,可环境覆盖
        # 关键:read-only 沙箱 + 在临时空目录里跑,codex 既改不了你的稿子、也读不到项目文件;
        # --skip-git-repo-check 避免它因"不在 git 仓库"而中断;最终回复写临时文件以拿到纯文本。
        with tempfile.TemporaryDirectory() as td:
            last = Path(td) / "last.txt"
            cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                   "--output-last-message", str(last)]
            if self.model:
                cmd += ["--model", self.model]
            cmd.append(prompt)
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=td)
            except subprocess.TimeoutExpired as e:
                raise LoomBackendError(render("codex_timeout", detail=f"timeout={timeout}s"),
                                       code="codex_timeout") from e
            except Exception as e:
                raise LoomBackendError(f"调用 codex 失败:{e}") from e
            if out.returncode != 0:
                raise LoomBackendError(render("codex_call_failed", detail=out.stderr.strip()[:500]),
                                       code="codex_call_failed")
            text = ""
            if last.exists():
                text = last.read_text(encoding="utf-8").strip()
            if not text:  # 兜底:--output-last-message 没写出来时退回 stdout
                text = out.stdout.strip()
        if not text:  # 跑完却没拿到正文 → 报错,别把空往下传
            raise LoomBackendError(render("backend_empty_response", detail=f"model={self.model or '默认'}"),
                                   code="backend_empty_response")
        return text


class DemoBackend:
    """录屏/试玩用的离线桩后端:不联网、不花钱,产出占位中文,让流水线真实点亮。

    用 LOOM_DEMO=1 开启。内容是占位,不代表真实生成质量。
    """

    def __init__(self, config: Config) -> None:
        self._chars = config.chapter_chars

    def _pick(self, system: str, user: str) -> str:
        head = system.strip().splitlines()[0]
        if "文风分析器" in system:
            return _DEMO["seed"]
        if "维护一个作者" in system:
            return _DEMO["learn"]
        if "剧情脊柱记录员" in system:
            return "摘要:(demo 占位摘要)。\n伏笔:\n- 无"
        if "起一个" in system or "章节标题" in system:  # 标题生成(demo 占位)
            return "废矿里的火光"
        for role, key in (("设定师", "anchor"), ("大纲师", "outline"),
                          ("写手", "draft"), ("编辑", "edit"), ("润色师", "final")):
            if role in head:
                return _DEMO[key]
        return "（demo 占位）"

    def complete(self, system: str, user: str, *, max_chars: int | None = None,
                 on_chunk: OnChunk | None = None) -> str:
        import time
        text = self._pick(system, user)
        if on_chunk is not None:  # 模拟流式:按小块吐,离线也能看见"一句句写出来"
            buf = ""
            for ch in text:
                buf += ch
                if len(buf) >= 6 or ch in "。\n!?！?":
                    on_chunk(buf)
                    buf = ""
                    time.sleep(0.02)
            if buf:
                on_chunk(buf)
            return text.strip()
        time.sleep(0.7)  # 让录屏里五个 agent 一个一个亮起来
        return text


_DEMO = {
    "seed": (
        "# 写作指纹\n\n## 句式偏好\n- 爱用短句,单句成段;很少用关联词焊接\n"
        "- 动作收尾,不解释情绪\n\n## 口头禅 / 高频表达\n- “他没说话。”\n- “就这样。”\n\n"
        "## 禁用词 / 绝不这么写\n- 殊不知、仿佛、宛如\n- 直接点名情绪\n\n## 节奏\n- 紧处短句快切,缓处一句带过\n\n"
        "## anchor 例句\n> 风停了。他把刀收回鞘里,没回头。\n"
    ),
    "learn": (
        "# 写作指纹\n\n## 句式偏好\n- 短句为主,单句成段;偏爱动作收尾\n- 对白只留半句,潜台词留给读者\n\n"
        "## 口头禅 / 高频表达\n- “他没说话。”\n- “就这样。”\n\n## 禁用词\n- 殊不知、仿佛、宛如;不直接点名情绪\n\n"
        "## 节奏\n- 紧处短句快切\n\n## anchor 例句\n> 风停了。他把刀收回鞘里,没回头。\n> 她笑了一下。那笑没到眼睛里。\n"
    ),
    "anchor": (
        "【本章设定锚点】\n- 涉及设定:灵气复苏第三年,主角觉醒“逆息”体质,只能在濒死时爆发。\n"
        "- 硬约束:逆息每用一次,寿元折损;不可滥用。\n- 人物状态:主角被逐出宗门,身负重伤,藏身废矿。\n"
        "- 接上一章钩子:追兵的火把已到矿口。"
    ),
    "outline": (
        "【本章场景骨头】\n1. 废矿·入口:火把逼近,主角屏息,伤口渗血。(蓄压)\n"
        "2. 矿道深处:追兵搜索,主角被逼到绝路。(更大压迫)\n"
        "3. 绝境:濒死触发逆息,一招逼退三人。(爆发·爽点)\n"
        "4. 章末:火光里走出一个不该出现的人——师姐。(悬念钩)"
    ),
    "draft": (
        "火把的光爬上矿壁。\n他屏住呼吸,后背贴着冰冷的石头。伤口又开了,血顺着指缝往下滴,一滴,一滴。\n"
        "“搜。”外面有人说。\n脚步声近了。他退,再退,退到矿道尽头,没路了。\n"
        "刀光劈下来的那一刻,胸口那点几乎熄灭的气,忽然烧了起来。\n"
        "逆息。\n他睁开眼。三个人影,一招之内,全倒了。\n矿道很静。他喘着气,握刀的手在抖。\n"
        "火光里,有人慢慢走进来。是个女人。\n“好久不见。”她说。\n他认得这个声音。"
    ),
    "edit": (
        "火把的光爬上矿壁。\n他屏住呼吸,后背贴着冰冷的石头。伤口又开了,血顺着指缝往下滴。\n"
        "“搜。”外面有人说。\n脚步声近了。他退到矿道尽头,没路了。\n"
        "刀光劈下来的那一刻,胸口那点快熄的气,忽然烧了起来。\n逆息。\n"
        "三个人影,一招之内全倒了。\n他喘着气,握刀的手在抖——这一下,又折了几年寿。\n"
        "火光里,一个女人慢慢走进来。\n“好久不见。”\n他认得这个声音。是师姐。"
    ),
    "final": (
        "火把的光爬上矿壁。\n他屏住呼吸,背贴着冷石。伤口又开了,血顺指缝往下滴。\n"
        "“搜。”\n脚步近了。他退到尽头,没路了。\n刀光下来那一刻,胸口快熄的那点气,烧了起来。\n"
        "逆息。\n三个人影,一招全倒。\n他喘着气,手在抖。这一下,又折了几年寿。\n"
        "火光里,一个女人走进来。\n“好久不见。”\n他认得这声音。\n是师姐。\n他没说话。"
    ),
}


def list_models(provider: str, *, base_url: str = "", api_key: str = "") -> dict:
    """列出某供应商可选模型。OpenAI 兼容的实时打 GET /models;CLI 类返回预设(别名自动跟最新)。

    只读、不发任何生成请求、不消耗 token。给「拉取可用模型」按钮用。
    """
    provider = (provider or "").lower()
    spec = PROVIDERS.get(provider)
    if not spec:
        return {"ok": False, "message": f"未知供应商 {provider}"}
    if spec["kind"] == "cli":
        return {"ok": True, "models": spec["models"], "source": "preset",
                "message": f"{spec['label']} 的可选模型(别名自动跟最新版本)"}
    burl = (base_url or "").strip() or (spec["base_url"] if spec.get("base_url_locked") else "") or spec.get("base_url", "")
    if not burl:
        return {"ok": False, "message": "先填 base_url 再拉取可用模型"}
    key = (api_key or "").strip() or os.environ.get(spec.get("key_env", ""), "")
    if not key:
        return {"ok": False, "message": "先填 API Key 再拉取可用模型"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=burl)
        resp = client.models.list()
        ids = sorted({m.id for m in resp.data})
        if not ids:
            return {"ok": False, "message": "这个 base_url 没返回任何模型(地址或 key 可能不对)"}
        return {"ok": True, "models": [{"id": i, "label": i} for i in ids], "source": "live",
                "message": f"拉到 {len(ids)} 个可用模型"}
    except Exception as e:
        return {"ok": False, "message": f"拉取失败:{e}"}


def probe(provider: str) -> dict:
    """轻量探活:命令在不在 PATH、能不能跑 --version、(codex)登没登录、(openai_compat)base_url+key 齐不齐。
    只跑本地命令 / 查本地配置,不发任何 LLM 请求、不消耗 token。给「检测连接」按钮用。"""
    provider = (provider or "deepseek").lower()
    if provider == "deepseek":
        return {"provider": provider, "ok": True, "kind": "key",
                "message": "DeepSeek 用 API Key 鉴权:把 key 填进右边、点「保存全局 Key」即可;需要本项目覆盖时点「保存后端」。"}
    if provider == "openai_compat":
        return {"provider": provider, "ok": True, "kind": "key",
                "message": "OpenAI 兼容供应商:填好 base_url + 模型名 + key,点「保存后端」;不确定模型名就点「拉取可用模型」。"}
    cmd = {"claude": "claude", "codex": "codex"}.get(provider)
    if not cmd:
        return {"provider": provider, "ok": False, "message": f"未知后端 {provider}"}
    if shutil.which(cmd) is None:
        hint = ("安装 Claude Code,确保 `claude` 在 PATH,并登录过一次"
                if provider == "claude"
                else "安装 Codex CLI:`npm i -g @openai/codex`,然后运行 `codex login`")
        return {"provider": provider, "ok": False, "installed": False,
                "message": f"没找到 `{cmd}` 命令", "hint": hint}
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=8)
        blob = (out.stdout or out.stderr).strip()
        ver = blob.splitlines()[0] if blob else cmd
    except Exception as e:
        return {"provider": provider, "ok": False, "installed": True,
                "message": f"`{cmd}` 跑不起来:{e}", "hint": "确认命令可用或重装"}
    if provider == "codex":  # codex 能查登录态,顺手确认一下
        try:
            st = subprocess.run([cmd, "login", "status"], capture_output=True, text=True, timeout=8)
            low = (st.stdout + st.stderr).lower()
            if "not logged in" in low or ("not" in low and "log" in low and "in" in low):
                return {"provider": provider, "ok": False, "installed": True, "version": ver,
                        "message": "Codex 已安装,但还没登录", "hint": "运行一次 `codex login`(复用 ChatGPT 订阅,不用填 key)"}
        except Exception:
            pass
        return {"provider": provider, "ok": True, "installed": True, "version": ver,
                "message": f"已就绪 · {ver}(复用 codex 客户端登录,不用填 key)"}
    return {"provider": provider, "ok": True, "installed": True, "version": ver,
            "message": f"已就绪 · {ver}(复用 claude 客户端登录,不用填 key)",
            "hint": "若从没登录过,终端先跑一次 `claude` 登录"}


def get_backend(config: Config) -> Backend:
    if os.environ.get("LOOM_DEMO"):
        return DemoBackend(config)
    provider = (config.provider or "deepseek").lower()
    if provider == "deepseek":
        return OpenAICompatBackend(config, "deepseek")
    if provider == "openai_compat":
        return OpenAICompatBackend(config, "openai_compat")
    if provider == "claude":
        return ClaudeCodeBackend(config)
    if provider == "codex":
        return CodexBackend(config)
    raise LoomBackendError(f"未知后端 provider={provider!r}(支持 deepseek/claude/codex/openai_compat)。")


def cheap_backend(config: Config) -> Backend | None:
    """便宜模型后端:仅当 cheap_model 设了且不同于主模型时返回(同 provider/base_url/key,只换 model);
    否则 None,调用方回退主后端。只给复审/写后摘要这类「评估/管 what」调用用,写作/学指纹始终留给主模型。"""
    import dataclasses
    cheap = (getattr(config, "cheap_model", "") or "").strip()
    if not cheap or cheap == (config.model or "").strip():
        return None
    return get_backend(dataclasses.replace(config, model=cheap))
