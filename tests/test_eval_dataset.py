"""Judge 校准数据集:schema 校验器。纯数据,零模型。"""
import json
from pathlib import Path

import pytest

from evals.dataset import (
    DIMENSIONS,
    DatasetError,
    SPLITS,
    discover_cases,
    load_case,
)


def _blank_labels(**overrides):
    """8 维全 present=False 的合法标注;overrides 按维度名替换单条。"""
    labels = [{"dimension": d, "present": False,
               "annotator": "构造注入(gold-by-construction)"} for d in DIMENSIONS]
    for dim, patch in overrides.items():
        for l in labels:
            if l["dimension"] == dim:
                l.update(patch)
    return labels


_DEFAULT_CONTEXT = {
    "setting": "灵气复苏,逆息体质忌讳外泄。", "characters": "沈砚:寡言,谋定后动。",
    "prev_hook": "上一章末:矿道尽头传来提灯脚步声。", "chapter_goal": "接钩+验伤+埋矿牌线。",
}


def _write_case(tmp_path, *, labels=None, split="dev", version=1, case_id="ds_x",
                 context=None, chapter="矿灯昏黄,沈砚验伤。他把旧矿牌收进怀里。"):
    d = tmp_path / "ds_x"; d.mkdir()
    case = {
        "split": split, "version": version,
        "source": {"origin": "constructed", "license": "self-authored", "deidentified": True},
        "context": context if context is not None else dict(_DEFAULT_CONTEXT),
        "labels": labels if labels is not None else _blank_labels(),
    }
    if case_id is not None:
        case["id"] = case_id
    (d / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "chapter.md").write_text(chapter, encoding="utf-8")
    return d


def test_dimensions_are_the_eight_judge_dims():
    assert DIMENSIONS == ("人物OOC", "设定漂移", "断钩子", "无爽点",
                          "信息边界", "物品状态连续性", "时间连续性", "AI腔")
    assert SPLITS == ("dev", "calibration", "holdout")


def test_clean_case_loads(tmp_path):
    case = load_case(_write_case(tmp_path))
    assert case["id"] == "ds_x" and len(case["labels"]) == 8


def test_missing_dimension_rejected(tmp_path):
    labels = _blank_labels()[:-1]                      # 只 7 条 → 维度不全
    with pytest.raises(DatasetError, match="维度"):
        load_case(_write_case(tmp_path, labels=labels))


def test_non_str_dimension_rejected_not_typeerror(tmp_path):
    # P2.T1 残留守卫的回归钉:8 条里混一个 int dimension(非单元素)——
    # 无守卫时 sorted([...str..., 123]) 裸 TypeError;守卫在→DatasetError。
    labels = _blank_labels()
    labels[3] = {"dimension": 123, "present": False, "annotator": "t"}
    with pytest.raises(DatasetError, match="字符串"):
        load_case(_write_case(tmp_path, labels=labels))


def test_chapter_evidence_must_be_substring(tmp_path):
    labels = _blank_labels(设定漂移={"present": True, "severity": "高",
                                    "evidence_type": "chapter", "evidence": "正文里根本没有这句",
                                    "note": "注入:境界名写错"})
    with pytest.raises(DatasetError, match="子串"):
        load_case(_write_case(tmp_path, labels=labels))


def test_absence_evidence_must_be_empty(tmp_path):
    labels = _blank_labels(断钩子={"present": True, "severity": "高",
                                  "evidence_type": "absence", "evidence": "不该有引文",
                                  "note": "注入:通章不接提灯脚步声的钩"})
    with pytest.raises(DatasetError, match="absence"):
        load_case(_write_case(tmp_path, labels=labels))


def test_valid_positive_case_loads(tmp_path):
    labels = _blank_labels(设定漂移={"present": True, "severity": "高",
                                    "evidence_type": "chapter", "evidence": "旧矿牌",
                                    "note": "示例:以子串核验通过为准"})
    case = load_case(_write_case(tmp_path, labels=labels))
    hit = [l for l in case["labels"] if l["present"]]
    assert len(hit) == 1 and hit[0]["dimension"] == "设定漂移"


def test_bad_split_rejected(tmp_path):
    with pytest.raises(DatasetError, match="split"):
        load_case(_write_case(tmp_path, split="test"))


def test_clean_label_must_not_carry_severity(tmp_path):
    labels = _blank_labels(时间连续性={"present": False, "severity": "低",
                                      "annotator": "构造注入(gold-by-construction)"})
    with pytest.raises(DatasetError, match="present=False"):
        load_case(_write_case(tmp_path, labels=labels))


# ---- Fix 轮补测试:version bool 洞 / id 缺失洞 / ctx 四键契约 / labels 项类型防御 / discover_cases ----

def test_version_bool_rejected(tmp_path):
    with pytest.raises(DatasetError, match="version"):
        load_case(_write_case(tmp_path, version=True))


def test_missing_id_rejected(tmp_path):
    with pytest.raises(DatasetError, match="id"):
        load_case(_write_case(tmp_path, case_id=None))


def test_context_extra_key_ignored_on_load(tmp_path):
    context = {**_DEFAULT_CONTEXT, "extra_count": 5}
    case = load_case(_write_case(tmp_path, context=context))
    assert case["id"] == "ds_x"


def test_context_evidence_from_extra_key_rejected(tmp_path):
    context = {**_DEFAULT_CONTEXT, "extra_note": "额外线索:小张的钥匙"}
    labels = _blank_labels(信息边界={"present": True, "severity": "中",
                                    "evidence_type": "context", "evidence": "小张的钥匙",
                                    "note": "注入:引用了四键之外的额外上下文"})
    with pytest.raises(DatasetError, match="子串"):
        load_case(_write_case(tmp_path, context=context, labels=labels))


def test_context_evidence_positive_path_loads(tmp_path):
    labels = _blank_labels(信息边界={"present": True, "severity": "中",
                                    "evidence_type": "context", "evidence": "矿道尽头传来提灯脚步声",
                                    "note": "示例:context 型 evidence 取自 prev_hook 子串"})
    case = load_case(_write_case(tmp_path, labels=labels))
    hit = [l for l in case["labels"] if l["present"]]
    assert len(hit) == 1 and hit[0]["dimension"] == "信息边界"


def test_label_item_must_be_object(tmp_path):
    labels = _blank_labels()
    labels[0] = "字符串坏项"
    with pytest.raises(DatasetError, match="对象"):
        load_case(_write_case(tmp_path, labels=labels))


def test_discover_cases_returns_sorted_paths(tmp_path):
    dataset_dir = tmp_path / "dataset"
    for cid in ("case_b", "case_a"):
        d = dataset_dir / "cases" / cid
        d.mkdir(parents=True)
        (d / "case.json").write_text("{}", encoding="utf-8")
    found = discover_cases(dataset_dir)
    assert found == sorted(found)
    assert [p.name for p in found] == ["case_a", "case_b"]


def test_discover_cases_empty_dir_returns_empty_list(tmp_path):
    assert discover_cases(tmp_path) == []


# ---- Task 2:rubric.md 文档-代码一致性(8 维标题逐字对齐 + 六节齐备 + 不打分红线) ----

def test_rubric_covers_every_dimension_verbatim():
    # rubric.md 的 8 个「## 维度名」标题必须与 DIMENSIONS 逐字一致(文档-代码单一来源)
    rubric = Path("evals/dataset/rubric.md").read_text(encoding="utf-8")
    for dim in DIMENSIONS:
        assert f"## {dim}" in rubric, f"rubric.md 缺维度小节:{dim}"
    for banned in ("总体文学分", "综合评分", "打分"):
        assert banned not in rubric, f"rubric 不许出现「{banned}」(ADR-0002 不打分红线)"


def test_rubric_each_dimension_has_required_parts():
    rubric = Path("evals/dataset/rubric.md").read_text(encoding="utf-8")
    for dim in DIMENSIONS:
        section = rubric.split(f"## {dim}")[1].split("\n## ")[0]
        for part in ("定义", "该抓(正例)", "不该抓(反例)", "边界例", "严重度", "证据要求"):
            assert part in section, f"{dim} 小节缺「{part}」"


# ---- Task 3:全数据集校验(一次写好,覆盖本任务与后续所有发货 case) ----

def test_shipped_dataset_all_cases_validate():
    # 仓库里实际发货的每个 case 都必须过校验器(含证据子串机械核验)。
    # Task 5 计划内断言演进:clean 负例加入后,「每例至少 1 维正例」不再成立,
    # 本测试退回纯 load 遍历(抛错即红);集级平衡由 test_dataset_v1_balance 钉死。
    dirs = discover_cases()
    assert dirs, "evals/dataset/cases 下还没有任何 case"
    for d in dirs:
        load_case(d)                                   # 逐例过校验器(抛错即红)


def test_dataset_v1_balance():
    cases = [load_case(d) for d in discover_cases()]
    by_dim_pos = {dim: 0 for dim in DIMENSIONS}
    clean_cases = 0
    splits = set()
    for c in cases:
        splits.add(c["split"])
        pos = [l for l in c["labels"] if l["present"]]
        if not pos:
            clean_cases += 1
        for l in pos:
            by_dim_pos[l["dimension"]] += 1
    assert all(n >= 1 for n in by_dim_pos.values()), f"每个维度至少 1 个正例:{by_dim_pos}"
    assert clean_cases >= 2, "至少 2 个干净难负例(压误报)"
    assert splits == set(SPLITS), f"三个 split 都要非空:{splits}"


# ---- Task 6:第二标注者空白工作表——诚实性钉死(present 不预填,由真人填) ----

def test_annotation_worksheet_template_structure():
    t = json.loads(Path("evals/dataset/annotations/worksheet_template.json").read_text(encoding="utf-8"))
    assert t["case_id"] == "" and t["annotator_id"] == ""
    assert [l["dimension"] for l in t["labels"]] == list(DIMENSIONS)
    assert all(l["present"] is None for l in t["labels"])      # 留给真人填,不预填
