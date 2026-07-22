"""M4 分卷 arc 轻量支持:领航员识别卡章纲 H2 卷级标题。"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from loom import paths
from loom.slots import _volume_slots, stage_slots
from loom.journey import STAGES, _CARD_LINE_RE


class TestVolumeParsing:
    """测试卷级标题解析。"""

    _VOLUME_RE = re.compile(r"^##\s*第(\d+)卷[·・.\s]*(.+?)\s*$", re.M)

    def test_volume_re_matches(self):
        """正则匹配 `## 第1卷·觉醒` 格式。"""
        text = "## 第1卷·觉醒\n- 第1章:开局\n- 第2章:发展\n## 第2卷·崛起\n- 第3章:高潮\n"
        matches = [(int(m.group(1)), m.group(2).strip()) for m in self._VOLUME_RE.finditer(text)]
        assert len(matches) == 2
        assert matches == [(1, "觉醒"), (2, "崛起")]

    def test_volume_re_no_match(self):
        """无卷级标题时不匹配。"""
        text = "- 第1章:开局\n- 第2章:发展\n"
        matches = list(self._VOLUME_RE.finditer(text))
        assert len(matches) == 0

    def test_volume_re_dot_variant(self):
        """容忍不同分隔符。"""
        text = "## 第1卷·觉醒\n## 第2卷・崛起\n## 第3卷.终章\n"
        matches = [(m.group(1), m.group(2).strip()) for m in self._VOLUME_RE.finditer(text)]
        assert len(matches) == 3

    def test_volume_re_ignores_chapters(self):
        """不把 `- 第1章` 误判为卷。"""
        text = "- 第1章:开局\n- 第2章:发展\n## 第1卷·觉醒"
        matches = [(m.group(1), m.group(2).strip()) for m in self._VOLUME_RE.finditer(text)]
        assert len(matches) == 1
        assert matches[0][0] == "1"
        assert matches[0][1] == "觉醒"
        assert int(matches[0][0]) == 1

    def test_card_line_re_matches(self):
        """`- 第N章:` 行正常匹配(不影响卷解析)。"""
        text = "## 第1卷·觉醒\n- 第1章:开局\n- 第2章:发展\n"
        assert _CARD_LINE_RE.search(text) is not None


class TestVolumeSlots:
    """测试 _volume_slots 函数。"""

    def test_no_card_file_returns_empty(self, project: Path):
        """卡章纲文件不存在时返回空列表。"""
        # 先删除卡章纲文件(如果有)
        card_p = project / paths.CARD_REL
        if card_p.exists():
            card_p.unlink()
        slots = _volume_slots(project, paths.CARD_REL)
        assert slots == []

    def test_no_volumes_returns_empty(self, project: Path):
        """卡章纲没有卷 H2 时返回空列表。"""
        card_p = project / paths.CARD_REL
        card_p.write_text("- 第1章:开局\n- 第2章:发展\n", encoding="utf-8")
        slots = _volume_slots(project, paths.CARD_REL)
        assert slots == []

    def test_single_volume(self, project: Path):
        """一个卷 H2 生成对应 slot。"""
        card_p = project / paths.CARD_REL
        card_p.write_text("## 第1卷·觉醒\n- 第1章:开局\n- 第2章:发展\n", encoding="utf-8")
        slots = _volume_slots(project, paths.CARD_REL)
        # 1 个卷 slot + 1 个汇总 slot
        assert len(slots) == 2
        vol_slot = slots[0]
        assert vol_slot.id == f"{paths.CARD_REL}#卷1"
        assert "第1卷·觉醒" in str(vol_slot.key)
        summary_slot = slots[1]
        assert summary_slot.id == f"{paths.CARD_REL}#@volumes"
        assert "共 1 卷" in str(summary_slot.hint)

    def test_multi_volume(self, project: Path):
        """多个卷 H2 生成多个 slot + 汇总。"""
        card_p = project / paths.CARD_REL
        card_p.write_text(
            "## 第1卷·觉醒\n- 第1章:开局\n- 第2章:发展\n"
            "## 第2卷·崛起\n- 第3章:高潮\n- 第4章:结局\n",
            encoding="utf-8"
        )
        slots = _volume_slots(project, paths.CARD_REL)
        # 2 个卷 slot + 1 个汇总 = 3
        assert len(slots) == 3
        assert slots[0].id == f"{paths.CARD_REL}#卷1"
        assert "卷1" in slots[0].id
        assert slots[1].id == f"{paths.CARD_REL}#卷2"
        assert "卷2" in slots[1].id
        assert "共 2 卷" in str(slots[2].hint)

    def test_volume_slots_are_filled(self, project: Path):
        """卷 slot 的 filled=True。"""
        card_p = project / paths.CARD_REL
        card_p.write_text("## 第1卷·觉醒\n- 第1章:开局\n", encoding="utf-8")
        slots = _volume_slots(project, paths.CARD_REL)
        for s in slots:
            assert s.filled is True


class TestStageSlotsWithVolumes:
    """测试 stage_slots 集成卷支持。"""

    def _card_spec(self):
        return next(s for s in STAGES if s.key == "卡章纲")

    def test_stage_slots_includes_volumes(self, project: Path):
        """stage_slots 卡章纲阶段包含卷 slot。"""
        card_p = project / paths.CARD_REL
        card_p.write_text(
            "## 第1卷·觉醒\n- 第1章:开局\n- 第2章:发展\n"
            "## 第2卷·崛起\n- 第3章:高潮\n",
            encoding="utf-8"
        )
        spec = self._card_spec()
        slots = stage_slots(project, spec)
        vol_ids = [s.id for s in slots if "卷" in s.id]
        assert len(vol_ids) >= 1
        assert f"{paths.CARD_REL}#卷1" in vol_ids
        assert f"{paths.CARD_REL}#卷2" in vol_ids

    def test_stage_slots_no_volume_falls_back(self, project: Path):
        """无卷 H2 时卡章纲阶段只有章行 slot。"""
        card_p = project / paths.CARD_REL
        card_p.write_text("- 第1章:开局\n- 第2章:发展\n", encoding="utf-8")
        spec = self._card_spec()
        slots = stage_slots(project, spec)
        # 只有章行 slots,没有卷 slots
        vol_ids = [s.id for s in slots if "卷" in s.id]
        assert len(vol_ids) == 0

    def test_stage_slots_other_stages_unaffected(self, project: Path):
        """非卡章纲阶段不受卷支持影响。"""
        from loom.journey import STAGES as stages
        for spec in stages:
            if spec.key != "卡章纲":
                slots = stage_slots(project, spec)
                assert all("卷" not in s.id for s in slots)


class TestVolumeInKandiji:
    """测试「看地基」工具能看到卷结构。"""

    def test_kandiji_includes_volumes(self, project: Path):
        """看地基输出包含卷信息。"""
        card_p = project / paths.CARD_REL
        card_p.write_text(
            "## 第1卷·觉醒\n- 第1章:开局\n- 第2章:发展\n"
            "## 第2卷·崛起\n- 第3章:高潮\n",
            encoding="utf-8"
        )
        from loom.partner_tools import _handle_kandiji
        result = _handle_kandiji(project)
        # 看地基输出应该包含卷结构信息
        assert "第1卷" in result
        assert "觉醒" in result
        assert "第2卷" in result
        assert "崛起" in result
        # 应该也包含章行
        assert "第1章" in result

    def test_kandiji_no_volumes_normal(self, project: Path):
        """无卷 H2 时看地基输出正常(不含卷)。"""
        card_p = project / paths.CARD_REL
        card_p.write_text("- 第1章:开局\n", encoding="utf-8")
        from loom.partner_tools import _handle_kandiji
        result = _handle_kandiji(project)
        # 不应该包含卷相关的信息
        assert "卷" not in result or "分卷" not in result


class TestJourneyVolumeAwareness:
    """测试 journey 对卷级结构的基本感知。"""

    def test_stage_done_allows_volumes_in_card(self, project: Path):
        """带卷级 H2 的卡章纲仍然被认为已完成。"""
        card_p = project / paths.CARD_REL
        card_p.write_text(
            "## 第1卷·觉醒\n- 第1章:开局\n",
            encoding="utf-8"
        )
        from loom.journey import STAGES, stage_done
        spec = next(s for s in STAGES if s.key == "卡章纲")
        assert stage_done(project, spec) is True
