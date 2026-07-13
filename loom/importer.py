"""导入铺底:把一堆非-Loom 的散装 md(资料夹)机械接成一本新 Loom 书。

红线(docs/design/proposals/导入铺底.md;CONTEXT.md「导入铺底」):纯机械搬运——
不调 LLM、不重塑内容(原样落盘)、不 AI 填立项卡/违禁词。硬设定/自动记忆不自动挂,
靠导入小结明示降级 + 作者事后用二期「世界观 AI 改写」手动归位。
"""

from __future__ import annotations

import re
import shutil

# 桶=外置大脑里作者可粘贴内容的文件(写作指纹刻意不在:它是 learn 蒸出的结构化文件,不接受原文)
BUCKETS = ("正文", "世界观", "人物", "卡章纲", "立项卡", "违禁词", "文风参考")

# 文件名关键词 → 桶。一份文件名撞到 >1 个桶,或一个都不撞 → unknown,交作者指认。
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("卡章纲", ("大纲", "章纲", "剧情", "分卷", "卷纲", "纲")),
    ("人物", ("人物", "角色", "主角", "配角", "反派", "小传", "人设")),
    ("世界观", ("设定", "世界", "力量", "体系", "境界", "地理", "势力", "金手指")),
    ("立项卡", ("立项", "定位", "平台")),
    ("违禁词", ("违禁", "敏感", "审核")),
    ("文风参考", ("文风", "范文", "风格")),
)


_BODY_NAME = re.compile(r"^第\s*(?:[0-9]+|[零〇一二两三四五六七八九十百千]+)\s*章")
_SERIAL_NAME = re.compile(r"^0*[0-9]+$")


def route_files(names: list[str]) -> dict[str, list[str]]:
    """文件名→桶。正文(第N章/纯序号)前置识别;.txt只准进正文,其余桶md-only。
    撞两桶或零命中 → unknown(含形似「写作指纹」的:它不是桶)。纯字符串,不读内容、不调 LLM。"""
    out: dict[str, list[str]] = {b: [] for b in BUCKETS}
    out["unknown"] = []
    for name in names:
        stem = name.rsplit(".", 1)[0]
        ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
        if _BODY_NAME.match(stem) or _SERIAL_NAME.match(stem):
            hit_kw = any(kw in stem for _, kws in _RULES for kw in kws)
            out["unknown" if hit_kw else "正文"].append(name)   # 第N章大纲/细纲/人物表→交作者指认,别当正文吞
            continue
        if ext == "txt":                 # 非正文的 txt → 让作者指认(设定桶不收 txt)
            out["unknown"].append(name)
            continue
        hit = [bucket for bucket, kws in _RULES if any(kw in stem for kw in kws)]
        if len(hit) == 1:
            out[hit[0]].append(name)
        else:
            out["unknown"].append(name)   # 撞多类/零类都让作者定
    return out


from pathlib import Path

from . import paths
from .fsutil import atomic_write_text

_FN_BAD = re.compile(r'[\\/:*?"<>|]')   # 文件名非法字符净化(同 draft._FN_BAD 口径)
_CH_LINE = re.compile(r"^-\s*第\S{0,6}章[:：]", re.M)

# 单文件桶:桶名 → 目标 rel(多份拼接进这一个文件)
_SINGLE = {"卡章纲": paths.CARD_REL, "立项卡": paths.PROJECT_CARD_REL,
           "违禁词": paths.BANNED_REL, "文风参考": paths.brain_rel("文风参考")}
# 目录桶:桶名 → 目标目录 rel(一份一文件)
_DIR = {"世界观": paths.WORLD_DIR_REL, "人物": paths.CHARS_DIR_REL}


def _clear_placeholders(dir_path: Path) -> None:
    """清掉目录桶里的出厂占位模板(留 成长档案.md=AI 自留地),免得真文件混着空模板。"""
    from .draft import _is_blank_or_template
    if not dir_path.is_dir():
        return
    for f in dir_path.glob("*.md"):
        if f.name != paths.GROWTH_NAME and _is_blank_or_template(f):
            f.unlink()


def _uniq(dir_path: Path, name: str) -> Path:
    """目录桶落盘防同名覆盖:已存在就 名·2.md、名·3.md…"""
    p = dir_path / name
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 2
    while p.exists():
        p = dir_path / f"{stem}·{i}{suffix}"
        i += 1
    return p


def _read_tolerant(p: Path) -> str:
    """拼接桶用:UTF-8→GBK→replace 兜底,永不崩;剥前导 BOM 免落进拼接中段。"""
    raw = p.read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc).lstrip("﻿")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").lstrip("﻿")


def _write_dir_file(src: Path, dst: Path) -> None:
    """目录桶落盘:UTF-8 源字节直拷(CRLF/BOM 原样保真);非 UTF-8(GBK 旧稿)转码成 UTF-8。
    ——Loom 全系统读盘按 UTF-8,GBK 字节直拷会让 studio/brain_ready 等严解码崩(发 GBK 稿即坏书)。"""
    raw = src.read_bytes()
    try:
        raw.decode("utf-8")            # UTF-8(含 BOM)可解 → 字节直拷,完全保真(verbatim 测试保绿)
        shutil.copyfile(src, dst)
    except UnicodeDecodeError:
        atomic_write_text(dst, _read_tolerant(src))   # GBK 等 → 转码 UTF-8(字符不变、字节变、可被 Loom 读)


def import_folder(folder: Path, name: str, routing: dict[str, list[str]], parent: Path) -> Path:
    """机械落盘:scaffold 建骨架 → 清收了文件的桶的占位 → 原样落他的 md。不改一个字、不调 LLM。"""
    from .scaffold import init as scaffold_init
    folder = Path(folder)
    root = scaffold_init(name, Path(parent))
    try:
        # 源文件按名索引(rglob 兜住他自己的子目录结构;同名以第一份为准,后续靠 _uniq 落不同名)
        by_name: dict[str, list[Path]] = {}
        for p in folder.rglob("*.md"):
            by_name.setdefault(p.name, []).append(p)
        for p in folder.rglob("*.txt"):
            by_name.setdefault(p.name, []).append(p)

        def _take(fname: str, used: dict[str, int]) -> Path | None:
            pool = by_name.get(fname, [])
            i = used.get(fname, 0)
            used[fname] = i + 1
            return pool[i] if i < len(pool) else None

        used: dict[str, int] = {}
        # 目录桶:UTF-8 源字节直拷(CRLF/BOM 原样保真);非 UTF-8(GBK)转码 UTF-8——
        # 全系统读盘按 UTF-8 严解码,字节直拷 GBK 会让下游 studio/brain_ready 崩(见 _write_dir_file)
        for bucket, dir_rel in _DIR.items():
            files = routing.get(bucket, [])
            if not files:
                continue
            d = root / dir_rel
            d.mkdir(parents=True, exist_ok=True)
            _clear_placeholders(d)
            for fname in files:
                src = _take(fname, used)
                if src is None:
                    continue
                safe = _FN_BAD.sub("·", fname) or "未命名.md"
                safe = Path(safe).stem + ".md"   # 设定桶 md-only:txt 指认进来也落成 .md,不成孤儿
                _write_dir_file(src, _uniq(d, safe))
        # 单文件桶:多份拼接 + 溯源头(拼接天然要 decode,容错读兜底,不崩、不把 BOM 落进中段)
        for bucket, rel in _SINGLE.items():
            files = routing.get(bucket, [])
            if not files:
                continue
            parts = []
            for fname in files:
                src = _take(fname, used)
                if src is None:
                    continue
                content = _read_tolerant(src)
                if content.strip():                          # 纯空白源跳过,免产裸「## 来自」头
                    parts.append(f"## 来自:{fname}\n\n{content}")   # content 不 strip,保他缩进/空行
            if parts:
                atomic_write_text(root / rel, "\n\n".join(parts) + "\n")
        # 正文桶:按真实章序重排、顺序归一为 第N章.md(阿拉伯章号是全系统规范);内容原样(txt 读容错落 md)
        body_files = routing.get("正文", [])
        if body_files:
            from .cnnum import chapter_order_key
            (root / paths.BODY_DIR).mkdir(parents=True, exist_ok=True)
            ordered = sorted(body_files, key=chapter_order_key)
            for i, fname in enumerate(ordered, start=1):
                src_p = _take(fname, used)
                if src_p is None:
                    continue
                _write_dir_file(src_p, paths.chapter_path(root, i))
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return root


def import_summary(root: Path, routing: dict[str, list[str]]) -> dict:
    """落盘后降级小结(只读,不调 LLM):各桶份数 + 降级提示。指路二期能力手动修。"""
    root = Path(root)
    placed = {b: len(routing.get(b, [])) for b in BUCKETS}
    notes: list[str] = []

    from .studio import names as _world_names
    # 世界观有内容却没识别到硬设定小节:用 studio.names 的世界观小节检测=硬设定直送同口径
    # (单一真相 _HARDFACT_KW/_SPOILER_KW、双形态、成长档案排除,且 sections 纯世界观不掺人物 roster)
    if placed["世界观"] and not _world_names(root).get("sections"):
        notes.append("世界观里没识别到硬设定小节(如「力量体系」「地理势力」),境界/专名这次没有逐字保护、"
                     "可能写漂——去左栏世界观里选中那段,用「AI 改写」把它单列成一节即可。")

    # 卡章纲有内容却不是「- 第N章:」一行格式 → 自动记忆不挂
    card_p = root / paths.CARD_REL
    if placed["卡章纲"] and card_p.is_file() and not _CH_LINE.search(card_p.read_text(encoding="utf-8")):
        notes.append("你的章纲是段落式,大纲师照读没问题、写正文不受影响;但「时间轴/伏笔账本」这类自动记忆"
                     "按「- 第N章:」一行格式挂,暂不显示——不影响写作。")
    # 正文落盘提示
    body_n = len(list((root / "正文").glob("第*章.md")))
    if body_n:
        notes.append(f"{body_n} 章正文已入库(按章序重排为 第1~{body_n}章)。")
        notes.append("导入的章不能 learn 属正常(learn 只学 AI 稿→你的手改,导入章没有 AI 原稿)。")
        notes.append("建议对最近几章跑一次「除虫」铺状态账本(可选,不强制)。")
    else:
        # 无正文 → 中性文风
        notes.append("你还没有正文,写作先用中性文风;写几章、手改后点 learn,会越来越像你(也可用 seed 从范文起手)。")
    return {"placed": placed, "notes": notes}
