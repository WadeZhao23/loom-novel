# 校准报告出处(report.json / report.md)

- 生成命令:`python -m evals.judge --backend configured --calibrate`
- 后端 / 模型:deepseek-v4-pro(直调,thinking mode 默认开)
- 数据集:evals/dataset/cases/(11 例,构造性金标)
- 代码 commit:603259e(合并 PR#7 后的 main)
- 生成日期:2026-07-19
- 整体 Judge-金标 κ:0.8231

## 诚实边界(必读,别当统计验证)
- **小样本**:每维度只有 1~2 个金标正例。recall=1.0 = "抓到了那 1 个例子",不是统计意义的验证。
- **构造性金标**:标签因缺陷是注入的而为真,不是人工共识。**人-人 κ 仍待标注**(需两名标注者按 ANNOTATION_GUIDE.md 标 calibration split),报告里 human_human_kappa 如实为「待标注」。
- **已知弱点**:AI腔 recall=0.5(漏 ds_09 孤立翻转句,rubric 缺口);人物OOC/设定漂移 precision=0.5(在 ds_05 一个坏 case 上过度归因)。
- **晋级范围**:据此只把「信息边界」(P=R=1.0)晋级 hard 做示范;设定漂移(precision 0.5)与其余保持 observe。数据集做大或有人工标注后再评扩。
