"""导入铺底:把一堆非-Loom 的散装 md(资料夹)机械接成一本新 Loom 书。

红线(docs/design/proposals/导入铺底.md;CONTEXT.md「导入铺底」):纯机械搬运——
不调 LLM、不重塑内容(原样落盘)、不 AI 填立项卡/违禁词。硬设定/自动记忆不自动挂,
靠导入小结明示降级 + 作者事后用二期「世界观 AI 改写」手动归位。
"""

from __future__ import annotations

import re

# 桶=外置大脑里作者可粘贴内容的文件(写作指纹刻意不在:它是 learn 蒸出的结构化文件,不接受原文)
BUCKETS = ("世界观", "人物", "卡章纲", "立项卡", "违禁词", "文风参考")

# 文件名关键词 → 桶。一份文件名撞到 >1 个桶,或一个都不撞 → unknown,交作者指认。
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("卡章纲", ("大纲", "章纲", "剧情", "分卷", "卷纲")),
    ("人物", ("人物", "角色", "主角", "配角", "反派", "小传", "人设")),
    ("世界观", ("设定", "世界", "力量", "体系", "境界", "地理", "势力", "金手指")),
    ("立项卡", ("立项", "定位", "平台")),
    ("违禁词", ("违禁", "敏感", "审核")),
    ("文风参考", ("文风", "范文", "风格")),
)


def route_files(names: list[str]) -> dict[str, list[str]]:
    """文件名启发路由。返回 {桶: [文件名], ..., "unknown": [文件名]}。
    撞两桶或零命中 → unknown(含形似「写作指纹」的:它不是桶)。纯字符串,不读内容、不调 LLM。"""
    out: dict[str, list[str]] = {b: [] for b in BUCKETS}
    out["unknown"] = []
    for name in names:
        stem = name.rsplit(".", 1)[0]
        hit = [bucket for bucket, kws in _RULES if any(kw in stem for kw in kws)]
        if len(hit) == 1:
            out[hit[0]].append(name)
        else:
            out["unknown"].append(name)   # 撞多类/零类都让作者定
    return out
