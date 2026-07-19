# annotations/ —— 人工标注落盘目录

## 现状(如实声明)

**目前这个目录里没有任何人工标注。** `worksheet_template.json` 是空白模板,不是数据。

`evals/dataset/cases/` 下每个 case 的 `case.json` 里已经有一份 `labels`,但那是 **v1 金标,
构造性得来**——缺陷是造数据的人先决定注入什么、再照着注入清单填的标签,标签为真是因为
"我们造了它",不是因为有独立的人看过文本、同意这是硬伤。目前还没有任何独立于构造过程的
人工判断验证过这批标签。

**人-人一致性(Cohen's κ,目标 ≥0.70)预注册于 Phase 3,现在还不存在这个数字。** 它要等
两名标注者按 `../ANNOTATION_GUIDE.md` 的流程,对 `calibration` split 的 case 各自独立标注、
互不参照之后,才能计算出来。在那之前,任何"这批金标是准的"之类的说法都没有实证支持——
只能说"标签内部自洽(校验器能过),但尚未经人工校准"。

## 这个目录以后会长什么样

标注者完成标注后,把工作表放进这里,命名为 `<case_id>.<annotator_id>.json`,例如:

```
annotations/ds_03_hook.zhang01.json
annotations/ds_03_hook.li02.json
```

同一个 case 出现两份不同 `annotator_id` 的文件,就是一组可以拿去算 κ 的独立标注对。
κ 计算脚本本身、以及标注完成后的一致性结果,属于 Phase 3 的工作,还没有开始。

## 怎么开始标注

见同级目录的 [`../ANNOTATION_GUIDE.md`](../ANNOTATION_GUIDE.md)。
