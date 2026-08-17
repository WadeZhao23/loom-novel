"""人格文件的两区结构:`## 基座`(包内模板)+ `## 个人增补`(refine 只写这里)。

设计(docs/superpowers/specs/2026-08-16-loom-continual-harness-design.md §5.2):

    ---
    name: 大纲师
    reads: ...
    ---
    <基座:出厂模板的正文。refine 永不碰,升级随包走>

    ## 个人增补
    <refine 写这里。一键清空即回出厂>

**形状不是新发明**——复用 `[AI补充]` 物理隔离块那套已验证做法(ADR 0007):只追加、
绝不覆盖人写的主体。同一个形状,换个落点。

红线:
- **基座永不重写**。Prime Agent 的 `/refine` 也守这条,理由一样:基座随包升级,被改过就
  再也升不动;增补是这本书这个作者的,清空就回出厂。
- **frontmatter 不进分区**。`reads:` 清单住在顶部 YAML 里,把它卷进正文 = 这个人格读不到
  任何设定。解析必须先把 frontmatter 摘出来、原样放回。
- 老书没有分区标记时**整份算基座**(增补为空),行为与加分区之前逐字一致——升级日零改动。
"""

from __future__ import annotations

from pathlib import Path

from .fsutil import atomic_write_text

EXTRA_HEAD = "## 个人增补"
_EXTRA_HINT = "(这一段由「让它更懂你」写入,记录你反复做的改法。可以手改,也可以一键清空回出厂。)"


def _path(root: Path | str, role: str) -> Path:
    p = Path(root) / "agents" / f"{role}.md"
    if not p.is_file():
        raise FileNotFoundError(f"找不到人格文件:{p}")
    return p


def _split_frontmatter(text: str) -> tuple[str, str]:
    """(frontmatter 原文含分隔线, 正文)。没有 frontmatter 则前者为空串。

    复刻 `agents._parse_frontmatter` 的切法但**不解析**——这里要的是原样保留,
    解析过一遍再拼回去会把用户的排版洗掉。
    """
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return "---" + parts[1] + "---", parts[2].lstrip("\n")


def split(root: Path | str, role: str) -> tuple[str, str]:
    """→ (基座正文, 个人增补)。没有增补区时增补为空串。"""
    body = _split_frontmatter(_path(root, role).read_text(encoding="utf-8"))[1]
    head = body.find(EXTRA_HEAD)
    if head == -1:
        return body.strip(), ""
    extra = body[head + len(EXTRA_HEAD):]
    # 提示行不算增补内容(它是写给作者看的说明,不该被当成学到的规则回喂进 refine)
    lines = [l for l in extra.splitlines() if l.strip() != _EXTRA_HINT]
    return body[:head].strip(), "\n".join(lines).strip()


def write_extra(root: Path | str, role: str, extra: str) -> Path:
    """整块替换个人增补区,基座一个字不动。

    是**替换**不是追加:refine 每次产出的是「并入之后的完整增补」(同 `fingerprint.learn`
    输出完整新指纹),追加会让同一条规则堆成流水账。
    """
    p = _path(root, role)
    fm, body = _split_frontmatter(p.read_text(encoding="utf-8"))
    base = split(root, role)[0]
    extra = (extra or "").strip()
    out = base if not extra else f"{base}\n\n{EXTRA_HEAD}\n{_EXTRA_HINT}\n\n{extra}"
    atomic_write_text(p, (f"{fm}\n{out}" if fm else out) + "\n")
    return p


def clear_extra(root: Path | str, role: str) -> Path:
    """清空增补 = 回出厂。基座本来就没被动过,所以这一步是无损的。"""
    return write_extra(root, role, "")
