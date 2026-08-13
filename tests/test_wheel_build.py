"""wheel 能否构建 + 运行时资源在不在里面 —— 2026-08-13 发现的 pre-existing 缺陷。

真事故:`pip install git+https://github.com/…@v0.4.4` 直接失败,
`ValueError: A second file is being added to the wheel archive at the same path:
loom/sample/.loom_state.json`。根因是 pyproject 里 packages=["loom"] 已经把整棵
loom/ 收进 wheel,又额外写了 force-include 把 templates/webui/sample 再加一遍。

为什么一直没人发现:实际分发走 PyInstaller 打的 Mac/Win 包,README 给开发者的也是
`pip install -e .`(可编辑安装不走 wheel 构建)。只有「从 git 直接装」这条路会踩到,
而这条路没人常走。实测 v0.4.2 起就坏着。

这条测试同时钉两件事:①wheel 构建得成功;②三个运行时必需目录不能因为去掉
force-include 而丢——它们是 agents 模板、Web UI、样例书,少一个产品就跑不起来。
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_RUNTIME_DIRS = ("loom/templates/", "loom/webui/", "loom/sample/")
_SPOT_CHECK = ("loom/templates/agents/写手.md", "loom/webui/index.html", "loom/sample/loom.toml")


def test_wheel_builds_and_carries_runtime_assets(tmp_path):
    try:
        import build  # noqa: F401
    except ModuleNotFoundError:
        pytest.skip("需要 `pip install build` 才能验证 wheel 构建")

    out = tmp_path / "dist"
    r = subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(_ROOT)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        "wheel 构建失败——最常见成因是有人给 pyproject 加回了 "
        "[tool.hatch.build.targets.wheel.force-include]:packages=['loom'] 已经收了整棵树,"
        f"再 force-include 会让同一路径添加两次。\nstderr:\n{r.stderr[-2000:]}")

    wheels = list(out.glob("*.whl"))
    assert wheels, "构建成功却没产出 .whl"
    names = zipfile.ZipFile(wheels[0]).namelist()
    for pre in _RUNTIME_DIRS:
        assert any(n.startswith(pre) for n in names), (
            f"wheel 里没有 {pre}——去掉 force-include 时把运行时资源一起弄丢了")
    for f in _SPOT_CHECK:
        assert f in names, f"wheel 缺运行时必需文件:{f}"
