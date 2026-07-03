"""loom.evalapi —— 给 evals/ 用的公共评测门面(稳定契约)。

evals 的 grader 要复用引擎里的几个检测/解析零件。此前它们直接 import
loom.fingerprint._segment、loom.gates._parse_verdict 这类私有符号——引擎侧一改名,
评测就悄悄坏。本模块把这些零件以公共稳定名导出,作为 evals ↔ loom 的唯一接缝:

- 引擎内部随便重构,但必须保住这里的名字和签名(改签名 = 改契约,先改这里再改 evals);
- evals 只准 import 本模块,不准伸手进 loom 的私有符号;
- 门面破了(名字丢了/背后实现改坏)evals 侧不降级:import 失败直接让
  `run_eval --gate` 红掉,验证方法见 evals/README.md「验证门禁真的会红」。

只服务开发者路径(evals / CI),不进产品运行时。
"""

from __future__ import annotations

from .aitell import detect as detect_aitell
from .fingerprint import _segment as segment_sentences
from .gates import CRITIC_去AI味, CRITIC_质检, Issue
from .gates import _parse_verdict as parse_critic_verdict

__all__ = [
    "CRITIC_去AI味",
    "CRITIC_质检",
    "Issue",
    "detect_aitell",
    "parse_critic_verdict",
    "segment_sentences",
]
