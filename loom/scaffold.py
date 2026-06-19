"""loom init:纯离线铺项目骨架(永不联网、永不因缺 key 失败)。

只负责建文件、返回路径。怎么展示(CLI 树 / GUI 列表)交给前端。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .fingerprint import neutral_default

TEMPLATES_DIR = Path(__file__).parent / "templates"
SAMPLE_DIR = Path(__file__).parent / "sample"  # 内置样例书《重生记忆》(2 章 + 进化过的指纹)
HIGHLIGHT = "外置大脑/写作指纹.md"  # 全片卖点
GENRE_DIR = "skills/题材"  # 题材库目录(相对项目根)


def open_sample(parent: Path | None = None) -> Path:
    """把内置样例书拷一份到 parent(默认当前目录),返回项目根;已存在就直接用那份。

    样例不带 .env(不含任何 key):打开是给陌生作者「看一本跑通的书」;想续写,填你自己的 DeepSeek key。
    """
    target = (parent or Path.cwd()) / "Loom样例-重生记忆"
    if not target.exists():
        shutil.copytree(SAMPLE_DIR, target)
    return target

# 别名归一:键=别名,值=正式题材文件名(不含 .md)
GENRE_ALIASES = {
    "玄幻": "修仙", "修真": "修仙", "玄幻修仙": "修仙",
    "都市修真": "都市异能",
    "游戏电竞": "电竞", "电竞文": "电竞",
    "直播": "直播文", "主播": "直播文", "直播带货": "直播文",
    "克系": "克苏鲁", "克系悬疑": "克苏鲁",
}


def _resolve_genre(genre: str | None) -> str | None:
    """归一题材名;命中不到模板就返回 None(永不报错,守离线铁律)。"""
    if not genre:
        return None
    name = GENRE_ALIASES.get(genre.strip(), genre.strip())
    return name if (TEMPLATES_DIR / GENRE_DIR / f"{name}.md").exists() else None


def available_genres() -> list[str]:
    """题材库里有哪些题材(供 CLI/WebUI 列选项)。"""
    d = TEMPLATES_DIR / GENRE_DIR
    return sorted(p.stem for p in d.glob("*.md") if p.stem != "README")


def init(name: str, parent: Path | None = None, genre: str | None = None) -> Path:
    """在 parent(默认当前目录)下建一个名为 name 的项目骨架,返回项目根路径。

    genre 命中题材库时,只把那一份题材速查拷进项目(没选/拼错则不拷,行为与不选一致)。
    """
    target = (parent or Path.cwd()) / name
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"目录 {target} 已存在且非空,换个名字或先清空。")

    # 全拷骨架,但排除整个题材目录(37 份不一把铺,按选中题材单拷)
    def _ignore(dir_path: str, names: list[str]) -> set[str]:
        if Path(dir_path).resolve() == (TEMPLATES_DIR / "skills").resolve():
            return {"题材"} & set(names)
        return set()

    shutil.copytree(TEMPLATES_DIR, target, dirs_exist_ok=True, ignore=_ignore)

    # 题材命中 → 只拷选中那一份(可手改、file-as-truth)
    chosen = _resolve_genre(genre)
    if chosen:
        dst = target / GENRE_DIR
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATES_DIR / GENRE_DIR / f"{chosen}.md", dst / f"{chosen}.md")

    # loom.toml 填上书名
    toml = target / "loom.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("__TITLE__", name), encoding="utf-8")

    # 写作指纹.md 离线落一份中性默认(不联网、不播种)
    (target / "外置大脑" / "写作指纹.md").write_text(neutral_default(), encoding="utf-8")

    # 正文/.原稿 先建好(AI 原稿快照将落在这里)
    (target / "正文" / ".原稿").mkdir(parents=True, exist_ok=True)
    gitkeep = target / "正文" / ".gitkeep"
    if gitkeep.exists():
        gitkeep.unlink()

    return target
