"""镜台:「它有多懂你」的只读投影——手改量双曲线 + 写作指纹 + 人格增补。

设计(docs/superpowers/specs/2026-08-17-镜台-design.md)。照 `studio.py` 的规矩:
**纯字符串切片,不调模型、不写盘、不打分**;markdown 仍是唯一真相,这里只是「读法」。
studio 投影的是**故事**(记不住前四十章),镜台投影的是**你**(它有多懂你)。

两条曲线的意义不同,分别对上产品的两轴:
- **改写率**(同位置换说法)↓ = 它越来越**像你** → 归写作指纹
- **增删率**(补/删信息)↓ = 它越来越**懂你要什么** → 归外置大脑 / 人格增补

红线:
- **只算 learn 过的章**。没 learn 的 0% 是「还没看」不是「不用改」;摆进曲线会让这个
  要当英雄指标用的数虚高,而虚高一次就再也不可信了。
- **句级对齐共用 `fingerprint.align_stats`**,绝不在这里另写一份。
- **绝不抛**:任一章坏掉就跳过它,其余照常返回(同 studio 的附赠类纪律)。
"""

from __future__ import annotations

from pathlib import Path

from . import paths
from .chaptertext import strip_title
from .fingerprint import align_stats
from .state import load_state


def _pair(root: Path, n: int) -> tuple[str, str] | None:
    """(AI 稿正文体, 作者改后正文体)。缺快照/读不了 → None(跳过该章,绝不抛)。"""
    snap, out = paths.snapshot_path(root, n), paths.chapter_path(root, n)
    if not snap.is_file() or not out.is_file():
        return None
    try:
        return (strip_title(snap.read_text(encoding="utf-8")),
                strip_title(out.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        # UnicodeDecodeError 继承自 ValueError 而非 OSError,裸 `except OSError` 抓不到,
        # 快照编码损坏时会直接抛穿、砸崩全书曲线——这里显式并列,不用裸 except Exception
        # (那会连编程错误一起吞掉,反而更难查)。
        return None


def curve(root: Path | str) -> list[dict]:
    """每章手改量的两条线。只含 learn 过、且有 AI 稿快照的章,按章号升序。"""
    root = Path(root)
    learned = set(load_state(root).get("learned", []))
    out: list[dict] = []
    for n in paths.chapter_numbers(root):
        if n not in learned:
            continue
        pair = _pair(root, n)
        if pair is None:
            continue
        ai, edited = pair
        st = align_stats(ai, edited)
        total = st["总句数"] or 1        # 空 AI 稿:分母兜 1,两个率自然是 0
        out.append({
            "章": n,
            "改写率": round(st["改写句数"] / total, 4),
            "增删率": round(st["增删句数"] / total, 4),
            "字数": len("".join(edited.split())),
        })
    return out


def coverage(root: Path | str) -> dict:
    """给作者的诚实交代:曲线只画了几章、为什么不是全部。"""
    root = Path(root)
    learned = set(load_state(root).get("learned", []))
    nums = paths.chapter_numbers(root)
    with_ai = [n for n in nums if paths.snapshot_path(root, n).is_file()]
    return {"已学": len([n for n in with_ai if n in learned]),
            "有稿": len(with_ai), "总章": len(nums)}


def fingerprint_view(root: Path | str) -> dict:
    """写作指纹这一块:来源 + 真规则行条数 + anchor 原句。

    「真规则行」的判据复用 `fingerprint._is_rule`(它已经把页眉说明与占位行排掉了)——
    不在这里另写一套「什么算一条规则」,否则镜台上的数字会和 learn 后的提示对不上。
    """
    from .fingerprint import _anchor_lines, _is_rule
    root = Path(root)
    src = load_state(root).get("fingerprint_source", "default")
    p = root / paths.FINGERPRINT_REL
    if not p.is_file():
        return {"来源": src, "规则数": 0, "anchor": []}
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # UnicodeDecodeError 继承自 ValueError 而非 OSError,同 `_pair` 那处的坑——
        # 裸 `except OSError` 抓不到,指纹文件编码损坏时会直接抛穿、砸崩全屏镜台。
        return {"来源": src, "规则数": 0, "anchor": []}
    rules = [l for l in text.splitlines() if _is_rule(l)]
    anchors = [l.strip().lstrip("> ").strip() for l in _anchor_lines(text)]
    return {"来源": src, "规则数": len(rules), "anchor": anchors}


def persona_view(root: Path | str) -> list[dict]:
    """人格增补这一块:按角色分组,只列**有增补**的角色。

    角色清单从 `artifacts.ARTIFACTS` 派生(产物表是产物侧的单一真相),不手抄五个名字。
    某个角色的文件缺失/读不了 → 跳过它,其余照常(绝不抛)。
    """
    from . import artifacts, persona
    root = Path(root)
    out: list[dict] = []
    for spec in artifacts.ARTIFACTS:
        if not spec.persona:
            continue
        try:
            extra = persona.split(root, spec.persona)[1]
        except (FileNotFoundError, OSError, UnicodeDecodeError):
            # UnicodeDecodeError 继承自 ValueError,同 fingerprint_view 那处的坑——
            # 人格文件编码损坏时裸 `except OSError` 抓不到,会抛穿砸崩全屏镜台。
            continue
        lines = [l.strip() for l in extra.splitlines() if l.strip().startswith("-")]
        if lines:
            out.append({"角色": spec.persona, "增补条数": len(lines), "增补": lines})
    return out


def mirror(root: Path | str) -> dict:
    """一次给全屏的四块。任一块自己兜底,不会因为某一块坏掉而整屏打不开。"""
    return {"曲线": curve(root), "指纹": fingerprint_view(root),
            "人格": persona_view(root), "覆盖": coverage(root)}
