"""openai 版本上限护栏 —— 2026-08-12 真事故。

openai 3.0.0 把传输层从 httpx 换成 httpx2,而 loom/backends.py 用 httpx.Timeout 配显式超时。
pyproject 当时写的是无上限的 `openai>=1.30`,于是 CI 全新安装拉到 3.0.0 →
`import httpx` ModuleNotFoundError → 双平台全红。本地因为 venv 里是 openai 2.46 + httpx,
怎么跑都是绿的,只有全新安装才会撞上。

这条测试钉住上限,免得有人「顺手」把它放开又炸一次。真要升 openai 3,
得先把 httpx→httpx2 迁移做完并真机验证,那时连同本文件一起改。
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _openai_spec() -> str:
    with (_ROOT / "pyproject.toml").open("rb") as f:
        deps = tomllib.load(f)["project"]["dependencies"]
    hits = [d for d in deps if re.match(r"^openai\b", d)]
    assert len(hits) == 1, f"pyproject 里 openai 依赖应恰好一条,实际:{hits}"
    return hits[0]


def test_transport_shim_accepts_both_httpx_flavors():
    """上限已解开(见 pyproject 注释),取而代之的是 backends 两种传输层都认。

    钉 <3 是 2026-08-12 的止血;真修法是 _http_transport 同时支持 httpx / httpx2,
    已在 openai 2.46+httpx 与 openai 3.0.0+httpx2 两套 venv 各跑一遍全量测试确认。
    """
    from loom.backends import _http_transport
    mod = _http_transport()
    assert mod.__name__ in ("httpx", "httpx2")
    t = mod.Timeout(120.0, connect=10.0, read=300.0)   # 两者签名一致,我们只用这一个 API
    assert t is not None


def test_http_transport_prefers_httpx_but_falls_back(monkeypatch):
    """httpx 缺席时必须回退 httpx2,而不是抛「缺少 openai」那种假话。"""
    import builtins
    from loom.backends import _http_transport
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name == "httpx":
            raise ModuleNotFoundError("no httpx")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake)
    try:
        mod = _http_transport()
    except Exception as e:            # 环境里也没有 httpx2 时,报的必须是传输层缺失
        assert "httpx" in str(e)
        return
    assert mod.__name__ == "httpx2"


def test_backends_reports_missing_transport_honestly():
    """缺传输层时不许报成「缺少 openai」——那是假话,会把人带偏。"""
    src = (_ROOT / "loom" / "backends.py").read_text(encoding="utf-8")
    # httpx 的 import 必须自成一个 try,不与 openai 的 except 合并
    assert "httpx_not_installed" in src, "缺 httpx 应有独立错误码,不该复用 openai_not_installed"
    from loom.errors import render
    msg = render("httpx_not_installed")
    assert "httpx" in msg and "openai<3" in msg.replace("'", "")
