"""计量代理:包住任意 Backend,记录每次 complete 的时延/输入输出字符数/system prompt。

Backend 协议(loom/backends.py:197)不回传 token 用量——OpenAI 兼容后端在
backends.py:293-296 丢弃 resp.usage,CLI 后端(claude/codex)只有文本 stdout。
所以 manifest 里 tokens/cost 诚实置 null,字符数是唯一可得的代理指标。
backend.complete 是五 Agent + 复审 + 起标题的唯一调用点,包代理即覆盖全部调用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class CallRecord:
    system_prompt: str
    user_chars: int
    output_chars: int
    max_chars: int | None
    elapsed_s: float


class MeteringBackend:
    """透明代理:行为与被包 backend 完全一致,只多记账;失败调用原样抛、不记账。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.records: list[CallRecord] = []

    def complete(self, system: str, user: str, *, max_chars=None, on_chunk=None, **kw) -> str:
        t0 = time.perf_counter()
        out = self.inner.complete(system, user, max_chars=max_chars, on_chunk=on_chunk, **kw)
        self.records.append(CallRecord(
            system_prompt=system, user_chars=len(user), output_chars=len(out),
            max_chars=max_chars, elapsed_s=round(time.perf_counter() - t0, 4)))
        return out
