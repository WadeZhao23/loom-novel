"""写盘安全闸:校验逻辑 + 保留旧文件不被空覆盖。"""
from __future__ import annotations

import pytest

from loom.backends import LoomBackendError
from loom.guard import FINGERPRINT, Profile, chapter_profile, guard_write, validate_output, visible_len


def test_empty_is_rejected():
    assert validate_output("", FINGERPRINT)
    assert validate_output("   \n  ", FINGERPRINT)


def test_too_short_is_rejected():
    assert validate_output("# 写作指纹\n## 句式\n短", FINGERPRINT)  # 有结构但实字太少


def test_missing_structure_is_rejected():
    long_no_marker = "这是一大段没有任何小节标题的文字。" * 10
    reasons = validate_output(long_no_marker, FINGERPRINT)
    assert any("结构" in r for r in reasons)


def test_valid_fingerprint_passes():
    good = ("# 写作指纹\n\n## 句式偏好\n- 爱用短句,单句成段。\n\n"
            "## anchor 例句\n> 风停了。他把刀收回鞘里,没回头。\n") * 1
    assert validate_output(good, FINGERPRINT) == []


def test_visible_len_ignores_whitespace():
    assert visible_len("  a b\n c ") == 3


def test_guard_write_preserves_old_file_on_empty(tmp_path):
    p = tmp_path / "fp.md"
    p.write_text("# 写作指纹\n## 句式偏好\n- 我攒下的嗓音。\n", encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    with pytest.raises(LoomBackendError) as e:
        guard_write(p, "", FINGERPRINT)
    assert e.value.code == "model_output_invalid"
    assert p.read_text(encoding="utf-8") == before   # 旧文件一字未动


def test_guard_write_writes_when_valid(tmp_path):
    p = tmp_path / "fp.md"
    good = "# 写作指纹\n\n## 句式偏好\n- 爱用短句,单句成段,动作收尾。\n\n## anchor 例句\n> 风停了。\n"
    guard_write(p, good, FINGERPRINT)
    assert "句式偏好" in p.read_text(encoding="utf-8")


def test_chapter_profile_scales_with_target():
    assert chapter_profile(1000).min_chars == 120
    assert chapter_profile(50).min_chars == 40   # 地板:宽松,只挡空/一句话
