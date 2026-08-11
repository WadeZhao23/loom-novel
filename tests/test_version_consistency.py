"""版本号两处必须一致——护栏测试。

背景(真事故):`pyproject.toml` 与 `loom/__init__.py` 各存一份版本号,发版流程要求两处一起改。
0.4.1 和 0.4.2 两次发版都只改了 `pyproject.toml`,漏了 `loom/__init__.py`(最后一次改停在
`4530de3 chore(release): 0.4.0`)。

后果不是"文档不一致"这种小事——`packaging/loom.spec` 里写着
「版本号单一真源 = loom/__init__.py 的 __version__」,`release.yml` 用它打包,
所以**已发布的 v0.4.1 / v0.4.2 的 Mac/Win 包自报版本号都是 0.4.0**:
用户 `loom --version` 打印 0.4.0,Web UI `/api/version` 也返回 0.4.0。

这条测试就是防它第三次发生。红了就是两处版本号不同步,改到一致即可。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import loom

_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    with (_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_pyproject_and_package_version_match():
    assert loom.__version__ == _pyproject_version(), (
        f"版本号两处不同步:pyproject.toml={_pyproject_version()} 但 "
        f"loom/__init__.py={loom.__version__}。发版要同时改这两处——"
        f"packaging/loom.spec 只读 loom/__init__.py,漏改会让打出来的包自报旧版本号。"
    )


def test_loom_spec_still_reads_version_from_package_init():
    """loom.spec 换成从别处读版本号时,本文件的理由就过期了——钉住这个前提。

    不是重复上一条:上一条断言「两个数相等」,这条断言「为什么必须相等」仍然成立。
    哪天真源改成 pyproject.toml,这条会红,提醒来人重写(而不是默默留下过期的注释)。
    """
    spec = (_ROOT / "packaging" / "loom.spec").read_text(encoding="utf-8")
    assert re.search(r"__version__", spec), (
        "packaging/loom.spec 不再从 loom/__init__.py 的 __version__ 读版本号了;"
        "test_version_consistency.py 的立论前提已变,请重写本文件的 docstring 与断言。"
    )
