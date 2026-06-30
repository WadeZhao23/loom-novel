"""loom 的离线 eval harness(开发期 / CI 工具,不是产品功能)。

一句话:在一个固定数据集上,用「确定性检测器 + LLM 复审」给引擎产出的章节打分,
聚合成通过率与各维度分,并和上一版基线比对——**改了 prompt / 换了模型 / 动了流水线后,
跑一遍就知道质量是涨了还是回归了**。

守 ADR-0002 / CONTEXT「过检测不当 KPI、不打分不阻断」:本 harness 评的是【引擎跨版本的回归】
(开发者/CI 用),**绝不在运行时给用户的书打分或阻断出稿**——和产品里的 gates 是两回事。
"""

from .harness import CaseResult, aggregate, run_case, run_suite  # noqa: F401
from .graders import GraderResult  # noqa: F401

__all__ = ["CaseResult", "GraderResult", "aggregate", "run_case", "run_suite"]
