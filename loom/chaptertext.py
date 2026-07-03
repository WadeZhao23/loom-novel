"""章节文档的标题/正文切分:正文首行 `# 标题` 作【单一真相】。

标题只存名字(不含「第N章」),章号由文件名/侧栏带——重编号搬文件即可,标题零改动。
纯字符串函数,不 import 任何 loom 模块,供 agents / fingerprint / server / rewrite 共用。

为什么把标题塞进正文文件、且 .原稿快照/ledger 都一并带上它:这样 chapter_drifted、
局部重写的外科式快照同步都保持口径一致(都含 H1),不会因为「正文有标题、快照没标题」
而恒判「手改过」。只有两处量「人手改了多少正文」的地方(learn 的 diff、侧栏「改过」徽标)
才先 strip_title 再比——这样【只改标题】不会被当成文风手改学进写作指纹。
"""

from __future__ import annotations


def split_title(text: str) -> tuple[str | None, str]:
    """拆出 (标题, 正文体)。首个非空行是 `# xxx` 才算标题,否则 (None, 原文)。

    老章(无 H1)→ (None, 原文),绝不凭空给它造标题。
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].lstrip().startswith("# "):
        title = lines[i].lstrip()[2:].strip()
        rest = lines[i + 1:]
        while rest and not rest[0].strip():   # 吃掉标题与正文之间的空行
            rest.pop(0)
        return (title or None), "\n".join(rest)
    return None, text


def parse_title(text: str) -> str | None:
    """取标题(没有则 None);给侧栏显示用。"""
    return split_title(text)[0]


def strip_title(text: str) -> str:
    """去掉首行标题只留正文体——用于 learn 的 diff 与「改过」判定,让改标题不污染文风学习。"""
    return split_title(text)[1]


def body_key(text: str) -> str:
    """归一化正文体(去首行标题、去首尾空白)——「手改判定」的统一口径。
    ledger 比的是落盘 sha,拿它归一后再哈希,与 body_changed 同一口径。"""
    return strip_title(text).strip()


def body_changed(a: str, b: str) -> bool:
    """正文体是否被手改(改标题不算)。server 侧栏「改过」徽标 / cli status /
    ledger.chapter_drifted 三处「手改判定」共用此谓词,口径永不漂移。"""
    return body_key(a) != body_key(b)


def compose(title: str | None, body: str) -> str:
    """把标题 + 正文体拼回章节文本(标题为空则只返回正文体)。不带尾换行,落盘处统一补。"""
    body = body.strip("\n")
    title = (title or "").strip().lstrip("#").strip()  # 容错:模型偶尔把 '# ' 也带进来
    if not title:
        return body
    return f"# {title}\n\n{body}"
