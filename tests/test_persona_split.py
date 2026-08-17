"""人格文件分两区:`## 基座`(包内模板,refine 永不碰)+ `## 个人增补`(refine 只写这里)。

spec 2026-08-16 §5.2。形状不是新发明——复用 `[AI补充]` 物理隔离块那套已验证做法
([ADR 0007](docs/adr/0007-external-brain-grows-with-story.md)):只追加、绝不覆盖人写的主体。
同一个形状,换个落点。

红线:**基座永不重写**。Prime Agent 的 `/refine` 明确「绝不重写基座提示词」,理由一样——
基座是随包升级的,被改过就再也升不动了;而增补是这本书/这个作者的,一键清空就能回出厂。
"""
from __future__ import annotations

import pytest

from loom import persona


def test_老书没有分区标记时整份当基座(project):
    """向后兼容:0.4.x 的 agents/*.md 没有分区标记。整份算基座、增补为空,
    行为与加分区之前逐字一致——升级日谁都不用改文件。"""
    body = (project / "agents/大纲师.md").read_text(encoding="utf-8")
    assert "## 基座" not in body          # 出厂模板本来就没有
    base, extra = persona.split(project, "大纲师")
    assert base.strip() and extra == ""
    assert "大纲师" in base


def test_写增补不碰基座(project):
    before = (project / "agents/大纲师.md").read_text(encoding="utf-8")
    persona.write_extra(project, "大纲师", "- 这本书默认拆三场,不拆四场。")
    base, extra = persona.split(project, "大纲师")
    assert "拆三场" in extra
    assert base.strip() in before or before.strip().endswith(base.strip()), "基座内容必须原样"


def test_再写一次增补是替换不是叠加(project):
    """增补区是【一份完整的增补】,不是流水账。refine 每次产出的是并入后的全文
    (同 fingerprint.learn 输出完整新指纹),这里就该整块替换。"""
    persona.write_extra(project, "大纲师", "- 第一版增补。")
    persona.write_extra(project, "大纲师", "- 第二版增补。")
    _, extra = persona.split(project, "大纲师")
    assert "第二版" in extra and "第一版" not in extra


def test_清空增补回到出厂(project):
    origin = (project / "agents/大纲师.md").read_text(encoding="utf-8")
    persona.write_extra(project, "大纲师", "- 一些增补。")
    persona.clear_extra(project, "大纲师")
    assert (project / "agents/大纲师.md").read_text(encoding="utf-8").strip() == origin.strip()


def test_frontmatter不被分区吃掉(project):
    """reads 清单住在顶部 YAML frontmatter 里,分区解析绝不能把它卷进正文。
    弄丢它 = 这个人格读不到任何设定。"""
    persona.write_extra(project, "大纲师", "- 增补一条。")
    from loom.agents import load_agent
    a = load_agent(project, "大纲师")
    assert "外置大脑/卡章纲.md" in a.reads
    assert "增补一条" in a.system_prompt, "增补要真的进 prompt,不然写了也白写"


def test_未知角色报错而不是默默新建(project):
    with pytest.raises(FileNotFoundError):
        persona.write_extra(project, "不存在的角色", "- x")
