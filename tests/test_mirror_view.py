"""镜台的另外两块:写作指纹 + 人格增补,以及一次给全屏的汇总出口。"""
from __future__ import annotations

from loom import mirror, paths, persona


def test_指纹块数出规则数与anchor原句(project):
    (project / paths.FINGERPRINT_REL).write_text(
        "# 写作指纹\n\n## 句式偏好\n- 爱用短句\n- 动作收尾\n\n"
        "## anchor 例句\n> 风停了。他把刀收回鞘里,没回头。\n> 她笑了一下。\n",
        encoding="utf-8")
    fp = mirror.fingerprint_view(project)
    assert fp["规则数"] == 4          # 2 条规则 + 2 条 anchor,都是「真规则行」
    assert "风停了。他把刀收回鞘里,没回头。" in fp["anchor"][0]
    assert len(fp["anchor"]) == 2


def test_指纹来源跟着state走(project):
    from loom.state import set_fingerprint_source
    set_fingerprint_source(project, "sample")
    assert mirror.fingerprint_view(project)["来源"] == "sample"


def test_指纹文件缺失时不炸(project):
    (project / paths.FINGERPRINT_REL).unlink()
    fp = mirror.fingerprint_view(project)
    assert fp["规则数"] == 0 and fp["anchor"] == []


def test_指纹文件编码损坏时不炸(project):
    """`fingerprint_view()` 与 `_pair()`(见 `test_mirror_curve.py`)同一个坑:
    `p.read_text(encoding="utf-8")` 读到非法字节时抛的是 `UnicodeDecodeError`,
    它继承自 `ValueError` 而非 `OSError`,裸 `except OSError` 抓不到——指纹文件
    编码损坏会直接抛穿、砸崩全屏镜台。正确行为是当成「没指纹」返回空结构。"""
    (project / paths.FINGERPRINT_REL).write_bytes(b"# \xff\xfe\n\xff\xfe")
    fp = mirror.fingerprint_view(project)               # 不抛
    assert fp["规则数"] == 0 and fp["anchor"] == []


def test_人格块只列有增补的角色(project):
    persona.write_extra(project, "大纲师", "- 默认拆三场。\n- 每场标字数。")
    view = mirror.persona_view(project)
    assert [p["角色"] for p in view] == ["大纲师"]
    assert view[0]["增补条数"] == 2
    assert "默认拆三场" in view[0]["增补"][0]


def test_缺agents文件不炸(project):
    (project / "agents/大纲师.md").unlink()
    persona.write_extra(project, "写手", "- 多用短句。")
    assert [p["角色"] for p in mirror.persona_view(project)] == ["写手"]


def test_人格文件编码损坏时跳过该角色不抛异常(project):
    """`persona_view()` 与 `fingerprint_view()` 同一个坑,换到人格文件上:`persona.split()`
    内部 `read_text(encoding="utf-8")` 读到非法字节时抛 `UnicodeDecodeError`,它继承自
    `ValueError` 而非 `OSError`,裸 `except OSError` 抓不到——某个角色的人格文件编码损坏
    会直接抛穿、砸崩全屏镜台。

    只断言「不抛」不够:同样违规的实现可以把整个列表一起拍空也不抛异常。这里必须同时
    验证——坏角色(设定师)被跳过、没出现在结果里;好角色(写手)正常写了增补,照常在。"""
    (project / "agents/设定师.md").write_bytes(b"# \xff\xfe\n\xff\xfe")
    persona.write_extra(project, "写手", "- 多用短句。")
    view = mirror.persona_view(project)                  # 不抛
    names = [p["角色"] for p in view]
    assert "设定师" not in names                          # 坏角色跳过
    assert "写手" in names                                # 好角色照常在
    assert view[names.index("写手")]["增补条数"] == 1


def test_汇总出口给全屏四块(project):
    got = mirror.mirror(project)
    assert set(got) == {"曲线", "指纹", "人格", "覆盖"}
    assert got["曲线"] == [] and got["人格"] == []
    assert got["覆盖"] == {"已学": 0, "有稿": 0, "总章": 0}
