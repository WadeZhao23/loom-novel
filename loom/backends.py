"""可插拔后端:一个 complete(system, user) -> str 的协议 + 三个实现。

v0.1 先把 DeepSeek 跑通(OpenAI 兼容)。Claude 走 `claude -p`。Codex 先 stub。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Protocol

from .config import Config
from .errors import render

# 流式回调:每收到一小段生成文本就调一次(让前端"看着它一句句写出来")。
OnChunk = Callable[[str], None]


class LoomBackendError(RuntimeError):
    """后端层的友好错误(CLI 会把它打成多段提示,而不是抛栈)。

    可选 code 指向 errors.py 的错误目录;不传时退化成普通字符串错误,向后兼容。
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class Backend(Protocol):
    def complete(self, system: str, user: str, *, max_chars: int | None = None,
                 on_chunk: OnChunk | None = None) -> str:
        """生成。给了 on_chunk 的后端会边生成边回调(流式);不支持流式的后端忽略它、结尾一次性返回。"""
        ...


class DeepSeekBackend:
    """DeepSeek:OpenAI 兼容接口,base_url=https://api.deepseek.com。"""

    def __init__(self, config: Config) -> None:
        self.model = config.model or "deepseek-chat"
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise LoomBackendError(render("deepseek_key_missing"), code="deepseek_key_missing")
        # 延迟 import,免得没装 openai 时连 --help 都跑不起来
        try:
            from openai import OpenAI
        except ModuleNotFoundError as e:
            raise LoomBackendError(render("openai_not_installed"), code="openai_not_installed") from e

        self._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    def complete(self, system: str, user: str, *, max_chars: int | None = None,
                 on_chunk: OnChunk | None = None) -> str:
        # 中文按 ~1.6 token/字 粗估,留点余量
        max_tokens = int(max_chars * 2.2) if max_chars else 2048
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
                return "".join(parts).strip()
            resp = self._client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=max_tokens, temperature=0.9,
            )
        except Exception as e:  # 网络/限流/鉴权 —— 统一收口成友好错误
            raise LoomBackendError(f"调用 DeepSeek 失败:{e}") from e
        return (resp.choices[0].message.content or "").strip()


class ClaudeCodeBackend:
    """接 Claude Code:把 system+user 拼成 prompt 走 `claude -p` headless。"""

    def __init__(self, config: Config) -> None:
        if shutil.which("claude") is None:
            raise LoomBackendError(render("claude_not_found"), code="claude_not_found")
        # 让 loom.toml 的 model 生效;没填/填了 deepseek 默认值时退回 sonnet(写文质量好,禁工具后仍是一次性补全)
        m = (config.model or "").strip()
        self.model = m if m and "deepseek" not in m else "sonnet"

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
        return out.stdout.strip()


class CodexBackend:
    """v0.1 占位。"""

    def __init__(self, config: Config) -> None:
        pass

    def complete(self, system: str, user: str, *, max_chars: int | None = None,
                 on_chunk: OnChunk | None = None) -> str:
        raise LoomBackendError("codex 后端 v0.1 还没接,先用 deepseek 或 claude。")


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


def get_backend(config: Config) -> Backend:
    if os.environ.get("LOOM_DEMO"):
        return DemoBackend(config)
    provider = (config.provider or "deepseek").lower()
    if provider == "deepseek":
        return DeepSeekBackend(config)
    if provider == "claude":
        return ClaudeCodeBackend(config)
    if provider == "codex":
        return CodexBackend(config)
    raise LoomBackendError(f"未知后端 provider={provider!r}(支持 deepseek/claude/codex)。")
