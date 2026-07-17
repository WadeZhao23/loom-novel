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
    # 退出码 1(质量回归)路径的单测覆盖(brief 缺、Task7 才验;这里补上,与 infra 的 2 区分)。
    # baseline 里塞一个当前数据集已无的 case → compare 反向遍历报「消失」→ 回归 → 1。
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({"cases": {"phantom_gone": {"score": 1.0, "passed": True}}}),
                  encoding="utf-8")
    assert main(["--gate", "--baseline-file", str(bf)]) == 1
