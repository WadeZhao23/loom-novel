"""标注包导出:结构上杜绝金标剧透(T6 审查发现)。"""
import json

from evals.dataset import discover_cases
from evals.export_packets import export_packet

_SPOILER = ("labels", "construction_note", "detector_note", "present", "severity", "annotator")


def test_export_packet_has_only_context_and_chapter(tmp_path):
    case_dir = discover_cases()[0]        # 用真实数据集第一个 case
    out = export_packet(case_dir, tmp_path)
    files = sorted(p.name for p in out.iterdir())
    assert files == ["chapter.md", "context.json"]
    ctx = json.loads((out / "context.json").read_text(encoding="utf-8"))
    assert set(ctx.keys()) == {"setting", "characters", "prev_hook", "chapter_goal"}


def test_export_packet_no_spoiler_anywhere(tmp_path):
    # 对所有 case 导出,逐字节扫描无任何剧透字段名
    for case_dir in discover_cases():
        out = export_packet(case_dir, tmp_path / case_dir.name)
        blob = (out / "context.json").read_text(encoding="utf-8")
        for word in _SPOILER:
            assert word not in blob, f"{case_dir.name} 导出包泄露字段 {word}"
