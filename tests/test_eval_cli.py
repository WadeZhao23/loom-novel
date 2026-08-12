"""run_eval CLI 退出码矩阵:0通过/1回归/2infra。零真实模型。"""
import json

from evals.run_eval import main


def test_no_cases_is_infra_2(tmp_path):
    assert main(["--cases", str(tmp_path), "--gate"]) == 2      # 空目录=infra,不是回归


def test_no_baseline_is_infra_2(tmp_path):
    # 有 case(默认数据集)但 baseline 文件不存在 → infra 2(不是 1)
    assert main(["--gate", "--baseline-file", str(tmp_path / "nope.json")]) == 2


def test_gate_pass_is_0():
    # 默认 cases + 默认 baseline(Task 3 已重固化)对齐 → 0
    assert main(["--gate"]) == 0


def test_baseline_and_gate_together_runs_gate(tmp_path, capsys):
    # --baseline --gate 单次同传:固化后必须继续跑门禁块(不再 early-return 静默跳过)。
    # 注:save 先于 gate、gate 比对的正是刚存的 baseline,故对齐必 0;用 stdout 含
    # 门禁判定行来证明「门禁块确实执行了」(旧代码 return 0 早退不会打印这行)。
    bf = tmp_path / "b.json"
    code = main(["--baseline", "--gate", "--baseline-file", str(bf)])
    out = capsys.readouterr().out
    assert code == 0
    assert "无回归" in out          # 门禁块跑到了 = 第三绕过面被堵


def test_gate_returns_1_on_regression(tmp_path):
    # 退出码 1(质量回归)路径的单测覆盖,与 infra 的 2 区分。
    # baseline 与数据集完全错位:3 个真 case 各报「未固化」+ phantom_gone 报「消失」→ regs 非空 → 1。
    # (「消失」路径的隔离验证在 test_eval_harness.py 的 test_deleted_baseline_case_flagged。)
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({"cases": {"phantom_gone": {"score": 1.0, "passed": True}}}),
                  encoding="utf-8")
    assert main(["--gate", "--baseline-file", str(bf)]) == 1


def test_judge_and_gate_are_mutually_exclusive(tmp_path, capsys):
    """--judge --gate 同传必须拒绝:LLM grader gating=True 会把权重和从 0.70 顶到 1.00,
    所有 case 分数整体位移,与 no-judge 基线比对必然伪回归。"""
    from evals.run_eval import main
    code = main(["--judge", "--gate", "--cases", str(tmp_path)])
    assert code == 2, "同传应判 infra(2),不是跑完再比"
    out = capsys.readouterr().out
    assert "--judge" in out and "--gate" in out


def test_all_cases_len_tolerance_is_capped():
    """字数容差封顶 0.25:超过它这个 grader 事实上不设防,不如老实标 observe。

    值本身是「先量后定」的——真机 gen_02 ×15 次终稿实测 |相对偏差| 最大 0.236
    (实际字数 764~1146,目标 1000),p90=0.199。0.25 刚好罩住实测分布、又留了牙齿。
    git 历史即「先跑基线后定值」的证据。
    """
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    bad = []
    for p in list((root / "evals" / "cases").glob("*/case.json")) + \
            list((root / "evals" / "gen_cases").glob("*/case.json")):
        tol = json.loads(p.read_text(encoding="utf-8")).get("expect", {}).get("len_tolerance")
        if tol is not None and tol > 0.25:
            bad.append(f"{p.parent.name}: {tol}")
    assert not bad, f"这些 case 的 len_tolerance 超过封顶 0.25:{bad}"
