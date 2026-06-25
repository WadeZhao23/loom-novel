"""模型输出写盘前的安全闸:校验-then-写,挡住空/残缺输出【静默覆盖】用户已攒下的数据。

根因(用户实报):换了个模型 → 后端返回空 → learn 把空串原样覆盖写作指纹,攒下的「你」被抹平。
这里给一切「模型输出 → 覆盖用户文件」的写盘点一道统一闸:不合格就【不写、保留旧文件、抛友好错误】。

纯校验逻辑 + 一个写盘包装。只 import errors / backends 的异常类型;backends 不反向 import 本模块(无环)。
注意职责切分:后端层只挡「完全空」(len==0);这里的 min_chars 管「太短/缺结构」——
正常输出永远过得了闸,只有真出问题的产出才会被拦下。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .backends import LoomBackendError
from .errors import render
from .fsutil import atomic_write_text


def visible_len(text: str) -> int:
    """去掉所有空白后的字符数——比 len() 更能反映「到底有没有实质内容」。"""
    return len("".join((text or "").split()))


@dataclass(frozen=True)
class Profile:
    label: str                       # 错误细节里的人话名字(写作指纹 / 正文 / 起草…)
    min_chars: int                   # 去空白后至少多少字才算「不是空响应」
    markers: tuple[str, ...] = field(default_factory=tuple)  # 必须命中其一的结构标记(空=不查结构)


def validate_output(candidate: str, profile: Profile) -> list[str]:
    """返回不合格原因列表(空列表 = 合格)。纯函数、零副作用,可单测。"""
    reasons: list[str] = []
    text = (candidate or "").strip()
    if not text:
        return [f"{profile.label}:模型这次返回空。"]   # 空就不必再查结构
    if visible_len(text) < profile.min_chars:
        reasons.append(f"{profile.label}:内容过短(实字不足 {profile.min_chars}),不像有效产出。")
    if profile.markers and not any(m in text for m in profile.markers):
        reasons.append(f"{profile.label}:缺少应有的结构(期望含「{profile.markers[0]}」这类小节)。")
    return reasons


def guard_write(path: Path, candidate: str, profile: Profile, *,
                code: str = "model_output_invalid", trailing_newline: bool = True) -> str:
    """校验通过才写盘(原子写),返回落盘后的文本;不通过则【保留旧文件不动】并抛友好错误。"""
    reasons = validate_output(candidate, profile)
    if reasons:
        raise LoomBackendError(render(code, detail="；".join(reasons)), code=code)
    text = candidate.strip()
    atomic_write_text(path, text + "\n" if trailing_newline else text)
    return text


def chapter_profile(target_chars: int) -> Profile:
    """正文画像:只挡「空/一句话」级别的残废产出,刻意宽松——

    数据丢失风险在于【空】(用户实报的是空字符串),而非「没写够目标字数」。
    一篇偏短但真实的正文成本极低(重跑即可),误杀它的代价更高,所以阈值压到目标字数的 12% + 地板 40。
    真正严的闸留给会覆盖你攒下数据的写作指纹(FINGERPRINT)。
    """
    return Profile("正文", min_chars=max(40, int(target_chars * 0.12)))


# 固定画像。FINGERPRINT 主要靠「有没有小节结构」判真假;min_chars 只兜「几乎空」,
# 刻意取低(30)以免误杀合法但精简的指纹——结构标记才是是不是一份指纹的强信号。
FINGERPRINT = Profile("写作指纹", min_chars=30, markers=("## ", "anchor", "句式"))
STEP = Profile("本章工序产物", min_chars=8)   # 流水线每棒:只挡空/拒答,各棒长短差异大不卡长度
DRAFT_SECTION = Profile("起草", min_chars=12)
