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
    elif t == "agent_chunk":
        import sys
        sys.stdout.write(event["delta"])  # 流式:边写边吐(调试用)
        sys.stdout.flush()
    elif t == "agent_done":
        console.print(f"\n[bold green]✓ {event['role']} Agent[/bold green] —— 已产出{event['produces']}")
    elif t == "agent_skip":
        console.print(f"[dim]⏭ {event['role']} —— 跳过(已完成、上游未变)[/dim]")
    elif t == "edit_note":
        console.print(f"  [dim]📝 本章改动留痕已存:{event['path']}[/dim]")
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
def init(name: str = typer.Argument(...),
         genre: str = typer.Option(None, "--题材", "--genre", help="选一个题材,只拷一份题材速查进项目")) -> None:
    from .scaffold import HIGHLIGHT, init as do_init

    try:
        target = do_init(name, genre=genre)
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
    from . import ledger
    from .agents import run_pipeline

    try:
        root = find_project_root()
        out = root / "正文" / f"第{chapter}章.md"
        if out.exists() and not force:
            if ledger.chapter_drifted(root, chapter):
                _die(f"第 {chapter} 章正文与上次记录不符(你手改过?)。先 learn {chapter},或加 --force 以你的正文为准重写。")
            _die(f"第 {chapter} 章已写完。要重写加 --force。")
        config = load_config(root)
        console.print(f"[dim]后端:{config.provider} · {config.model} · 终稿≈{config.chapter_chars}字[/dim]\n")
        # out 不存在=上次没跑完(断点),resume 跳过已落盘且上游未变的工序,省 DeepSeek 计费
        run_pipeline(root, chapter, get_backend(config), config, _render, slow=0.3, resume=not force)
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


@app.command(help="启动自检:检查 key/后端命令/agent/外置大脑齐不齐。")
def doctor() -> None:
    from .doctor import run_checks

    try:
        root = find_project_root()
    except FileNotFoundError as e:
        _die(str(e))
    checks = run_checks(root)
    if all(c.ok for c in checks):
        console.print("[bold green]✓ 环境就绪,可以开写。[/bold green]")
        raise typer.Exit(0)
    table = Table(title="启动自检 · 待修复")
    for col in ("检查项", "缺什么", "怎么补"):
        table.add_column(col)
    for c in checks:
        if not c.ok:
            table.add_row(f"[red]✗ {c.name}[/red]", c.missing, c.fix)
    console.print(table)
    raise typer.Exit(1)


@app.command(help="离线拆一本参考书,抽可迁移框架(产物是候选,不进流水线)。")
def deconstruct(source: Path = typer.Argument(..., help="参考书文本路径"),
                name: str = typer.Option(None, "--名", "--name")) -> None:
    from .deconstruct import deconstruct as do_deconstruct

    try:
        root = find_project_root()
        if not source.exists():
            _die(f"参考书文件不存在:{source}")
        text = source.read_text(encoding="utf-8")
        label = name or source.stem
        out = do_deconstruct(root, text, label, get_backend(load_config(root)), _render)
        console.print(Panel(
            "产物在 [bold]外置大脑/.拆书/[/bold],只是候选。\n"
            "要用:亲手把'条件框架'抄进 世界观.md;[red]专名黑名单别抄,写作指纹.md 永远别动[/red]。",
            title=f"✓ 已拆:{label} → {out.name}", border_style="yellow"))
    except (LoomBackendError, FileNotFoundError, ValueError) as e:
        _die(str(e))


@app.command(help="打印版本。")
def version() -> None:
    console.print(f"loom {__version__}")


if __name__ == "__main__":
    app()
