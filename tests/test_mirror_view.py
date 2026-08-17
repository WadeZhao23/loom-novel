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


def test_汇总出口给全屏四块(project):
    got = mirror.mirror(project)
    assert set(got) == {"曲线", "指纹", "人格", "覆盖"}
    assert got["曲线"] == [] and got["人格"] == []
    assert got["覆盖"] == {"已学": 0, "有稿": 0, "总章": 0}
