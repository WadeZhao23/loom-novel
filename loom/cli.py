"""loom 的内部调试 CLI(产品形态是桌面客户端,见 docs/adr/0004)。

保留它是为了无界面快速验证引擎。命令:init / seed / write / learn / status。
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from . import __version__
from .backends import LoomBackendError, get_backend
from .config import find_project_root, load_config
from .state import load_state

app = typer.Typer(add_completion=False, no_args_is_help=True, help="loom 引擎调试 CLI(产品是桌面客户端)")
console = Console()


def _die(msg: str) -> None:
    console.print(f"[bold red]✗[/bold red] {msg}")
    raise typer.Exit(code=1)


def _render(event: dict) -> None:
    """把引擎进度事件渲染成 Rich 输出。"""
    t = event.get("type")
    if t == "agent_start":
        console.print(f"[bold cyan]▶ {event['role']} Agent[/bold cyan] …")
    elif t == "agent_done":
        console.print(f"[bold green]✓ {event['role']} Agent[/bold green] —— 已产出{event['produces']}")
    elif t == "warn":
        console.print(f"  [yellow]· {event['message']}[/yellow]")
    elif t == "info":
        console.print(f"[cyan]▶ {event['message']}[/cyan]")
    elif t == "chapter_done":
        console.print()
        console.print(Panel(event["preview"] + ("…" if event["chars"] > 300 else ""),
                            title=f"第{event['chapter']}章 · 终稿前 300 字", border_style="green"))
        console.print(f"[bold]终稿已落:[/bold] {event['path']}")
    elif t in ("seed_done", "learn_done"):
        console.print(f"[green]✓ 写作指纹已更新:[/green] {event['path']}")


@app.command(help="离线铺一个写小说项目的骨架。")
def init(name: str = typer.Argument(...)) -> None:
    from .scaffold import HIGHLIGHT, init as do_init

    try:
        target = do_init(name)
    except (FileExistsError, FileNotFoundError) as e:
        _die(str(e))
    tree = Tree(f"[bold]{target.name}/[/bold]")
    _walk(tree, target, target, HIGHLIGHT)
    console.print(tree)
    console.print(f"\n[green]✓ 骨架已就位(离线)。[/green] cd {name},填 .env,再 seed / write。")


def _walk(node: Tree, path: Path, base: Path, highlight: str) -> None:
    for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
        if child.name in (".原稿", ".loom_state.json"):
            continue
        rel = str(child.relative_to(base))
        if child.is_dir():
            _walk(node.add(f"[blue]{child.name}/[/blue]"), child, base, highlight)
        elif rel == highlight:
            node.add(f"[bold yellow]★ {child.name}[/bold yellow]  [dim]← 越写越像你的核心[/dim]")
        else:
            node.add(child.name)


@app.command(help="从样本提炼写作指纹。")
def seed(sample: Path = typer.Option(None, "--样本", "--sample", "-s"),
         text: str = typer.Option(None, "--文本", "--text"),
         inherit: Path = typer.Option(None, "--继承", "--inherit")) -> None:
    from .fingerprint import seed_from_inherit, seed_from_samples

    try:
        root = find_project_root()
        if inherit is not None:
            seed_from_inherit(root, inherit, _render)
            return
        if sample is not None:
            if not sample.exists():
                _die(f"样本文件不存在:{sample}")
            text = sample.read_text(encoding="utf-8")
        if not text:
            _die("给我点料:--样本 文件 / --文本 '一段字' / --继承 另一本书的指纹。")
        seed_from_samples(root, text, get_backend(load_config(root)), _render)
    except (LoomBackendError, FileNotFoundError, ValueError) as e:
        _die(str(e))


@app.command(help="跑 5 个 Agent 写第 N 章。")
def write(chapter: int = typer.Argument(...), force: bool = typer.Option(False, "--force", "-f")) -> None:
    from .agents import run_pipeline

    try:
        root = find_project_root()
        out = root / "正文" / f"第{chapter}章.md"
        snap = root / "正文" / ".原稿" / f"第{chapter}章.md"
        if out.exists() and not force:
            edited = snap.exists() and out.read_text(encoding="utf-8").strip() != snap.read_text(encoding="utf-8").strip()
            if edited:
                _die(f"第 {chapter} 章你手改过,重跑会覆盖。先 learn {chapter},或加 --force。")
            _die(f"第 {chapter} 章已存在。要重写就加 --force。")
        config = load_config(root)
        console.print(f"[dim]后端:{config.provider} · {config.model} · 终稿≈{config.chapter_chars}字[/dim]\n")
        run_pipeline(root, chapter, get_backend(config), config, _render, slow=0.3)
    except (LoomBackendError, FileNotFoundError, ValueError) as e:
        _die(str(e))


@app.command(help="把你对第 N 章的手改蒸馏进指纹。")
def learn(chapter: int = typer.Argument(...)) -> None:
    from .fingerprint import learn as do_learn

    try:
        root = find_project_root()
        do_learn(root, chapter, get_backend(load_config(root)), _render)
    except (LoomBackendError, FileNotFoundError, ValueError) as e:
        _die(str(e))


@app.command(help="看项目状态。")
def status() -> None:
    try:
        root = find_project_root()
    except FileNotFoundError as e:
        _die(str(e))
    st = load_state(root)
    src = {"default": "中性默认(还没懂你)", "sample": "你的样本", "inherit": "继承自另一本书"}.get(
        st.get("fingerprint_source", "default"), st.get("fingerprint_source"))
    console.print(f"[bold]写作指纹来源:[/bold] {src}")
    learned = set(st.get("learned", []))
    body = root / "正文"
    chapters = sorted(int(p.stem[1:-1]) for p in body.glob("第*章.md")) if body.exists() else []
    if not chapters:
        console.print("[dim]还没写任何一章。[/dim]")
        return
    table = Table(title="章节状态")
    for c in ("章", "写了", "你改过", "学进指纹"):
        table.add_column(c)
    for n in chapters:
        out, snap = body / f"第{n}章.md", body / ".原稿" / f"第{n}章.md"
        edited = snap.exists() and out.read_text(encoding="utf-8").strip() != snap.read_text(encoding="utf-8").strip()
        table.add_row(f"第{n}章", "✓", "[green]✓[/green]" if edited else "—", "[green]✓[/green]" if n in learned else "—")
    console.print(table)


@app.command(help="打印版本。")
def version() -> None:
    console.print(f"loom {__version__}")


if __name__ == "__main__":
    app()
