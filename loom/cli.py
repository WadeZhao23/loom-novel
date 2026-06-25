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
        _render._streamed = False
        console.print(f"[bold cyan]▶ {event['role']} Agent[/bold cyan] …")
    elif t == "agent_chunk":
        import sys
        sys.stdout.write(event["delta"])  # 流式:边写边吐(调试用)
        sys.stdout.flush()
        _render._streamed = True
    elif t == "agent_done":
        nl = "\n" if getattr(_render, "_streamed", False) else ""  # 只有真流式过才补收尾换行
        console.print(f"{nl}[bold green]✓ {event['role']} Agent[/bold green] —— 已产出{event['produces']}")
    elif t == "agent_skip":
        console.print(f"[dim]⏭ {event['role']} —— 跳过(已完成、上游未变)[/dim]")
    elif t == "gate_start":
        if getattr(_render, "_streamed", False):
            console.print()
            _render._streamed = False  # 让复审标题另起一行,不黏在上游流式稿尾
        console.print(f"  [magenta]🔍 {event['label']}复审 · 第{event['round']}轮[/magenta] …")
    elif t == "gate_pass":
        console.print(f"  [green]✓ {event['label']}通过[/green] [dim](无硬伤)[/dim]")
    elif t == "gate_issues":
        console.print(f"  [yellow]发现 {len(event['issues'])} 处硬伤:[/yellow]")
        for it in event["issues"]:
            ev = f" [dim]｜证据:「{it['证据']}」[/dim]" if it.get("证据") else ""
            console.print(f"    [yellow]·[/yellow] {it['类别']}:{it['问题']}{ev}")
    elif t == "gate_revise":
        console.print("  [magenta]↻ 回炉重写中…[/magenta]")
    elif t == "gate_exhausted":
        console.print(f"  [yellow]⚠ {event['label']}跑满 {event['rounds']} 轮仍有 "
                      f"{len(event['issues'])} 处残留 → 已记入留痕,不阻断,继续[/yellow]")
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


@app.command(help="拷一份内置样例书《重生记忆》到当前目录,看看一本跑通的书。")
def sample() -> None:
    from .scaffold import open_sample

    root = open_sample()
    console.print(f"[green]✓ 样例书已就位:[/green] {root}")
    console.print("[dim]2 章正文 + 进化过的写作指纹 + 外置大脑都在。想续写,填你自己的 DeepSeek key。[/dim]")


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
    from .fingerprint import changed_rules
    from .fingerprint import learn as do_learn

    try:
        root = find_project_root()
        fp = root / "外置大脑" / "写作指纹.md"
        old = fp.read_text(encoding="utf-8") if fp.exists() else ""
        do_learn(root, chapter, get_backend(load_config(root)), _render)
        ch = changed_rules(old, fp.read_text(encoding="utf-8"))
        if ch["added"] or ch["removed"]:
            console.print("\n[bold]本次指纹变化[/bold] [dim](学歪了?在 app 里点撤销,或删 外置大脑/.指纹历史/)[/dim]")
            for l in ch["removed"]:
                console.print(f"  [red]− {l}[/red]")
            for l in ch["added"]:
                console.print(f"  [green]+ {l}[/green]")
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
    from .chaptertext import parse_title, strip_title
    table = Table(title="章节状态")
    for c in ("章", "标题", "写了", "你改过", "学进指纹"):
        table.add_column(c)
    for n in chapters:
        out, snap = body / f"第{n}章.md", body / ".原稿" / f"第{n}章.md"
        out_text = out.read_text(encoding="utf-8")
        # 「改过」只看正文体(去标题再比),与 learn/drift 同口径:改标题不算手改
        edited = snap.exists() and strip_title(out_text).strip() != strip_title(snap.read_text(encoding="utf-8")).strip()
        table.add_row(f"第{n}章", parse_title(out_text) or "[dim]—[/dim]", "✓",
                      "[green]✓[/green]" if edited else "—", "[green]✓[/green]" if n in learned else "—")
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


@app.command(help="把全书正文导出成一个 txt(发平台 / 留档用)。")
def export() -> None:
    from .archive import export_text

    try:
        r = export_text(find_project_root())
        console.print(f"[green]✓ 已导出 {r['chapters']} 章、{r['chars']} 字:[/green] {r['path']}")
    except (FileNotFoundError, ValueError) as e:
        _die(str(e))


@app.command(help="把整本书打包成 zip 备份(不含密钥)。记得拷到云盘/U盘才算真备份。")
def backup() -> None:
    from .archive import backup_project

    try:
        r = backup_project(find_project_root())
        console.print(f"[green]✓ 已备份:[/green] {r['path']}  [dim]({r['size'] // 1024} KB,留最近 {r['kept']} 份)[/dim]")
        console.print("[yellow]提醒:把这个 zip 拷到云盘/U盘,才算真备份。[/yellow]")
    except (FileNotFoundError, ValueError) as e:
        _die(str(e))


@app.command(help="打印版本。")
def version() -> None:
    console.print(f"loom {__version__}")


if __name__ == "__main__":
    app()
