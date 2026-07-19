# 人工标注指南(写给第二标注者)

你不需要了解这个仓库的任何其他部分。本指南是自包含的:照着做完,你的产出就是一组
`annotations/<case_id>.<annotator_id>.json` 文件。

## 这是什么、为什么需要你

`evals/dataset/cases/` 下的每个 case 都已经有一份「金标」标注,写在 `case.json` 的
`labels` 字段里。但那份金标是**构造性的**——它是由造这批数据的人「先决定注入什么缺陷,
再照着注入清单填标签」得来的,标签为真是因为缺陷是造的,不是因为有第二个人独立看过文本、
同意「这里确实是硬伤」。

这意味着现在还没有任何证据表明:换一个人独立看这份 chapter,会不会做出同样的判断。
你的标注,就是用来回答这个问题的第一份独立证据。Phase 3 会用你和另一位标注者在同一批
case 上的独立结果算 Cohen's κ(人-人一致性),目标 ≥0.70。在那之前,这个数字不存在——
所以请认真对待每一条判断,你写下的就是将来用来验证整个 rubric 是否可操作的原始数据。

## 标注单位

一个 case = 一个目录 `evals/dataset/cases/<case_id>/`,里面有:

- `case.json` —— **只准看 `context` 字段的四个键**(`setting` / `characters` /
  `prev_hook` / `chapter_goal`)。**除这四键之外,`case.json` 里的任何字段都不要看**——
  包括但不限于 `labels`(本 case 的金标答案)、`construction_note` / `detector_note`
  (造数据者逐维记录的裁决理由,内容等同于金标剧透)、以及未来可能新增的任何其他字段。
  这些字段都可能携带金标信息,提前看到等于抄答案,你的标注就失去了作为独立证据的意义。
  如果你不小心看到了 `context` 以外的任何字段内容(不限于 `labels`),换一个还没看过
  的 case,并在该 case 的 note 里如实记录「已看过 `<字段名>`,本次标注作废」。

  **最稳的做法:不要自己打开 `case.json`。** 请标注协调者(仓库维护者)用命令行把
  `context` 四键与 `chapter.md` 单独导出成一份不含 `labels`/`construction_note`/
  `detector_note` 的临时标注包,再发给你,而不是让你直接打开 `case.json`。例如维护者
  可以这样为单个 case 导出:

  ```bash
  .venv/bin/python -c "
  import json, pathlib
  case_id = 'ds_11_clean_setup'
  src = pathlib.Path(f'evals/dataset/cases/{case_id}')
  dst = pathlib.Path(f'/tmp/annotate_export/{case_id}')
  dst.mkdir(parents=True, exist_ok=True)
  case = json.load(open(src / 'case.json', encoding='utf-8'))
  (dst / 'context.json').write_text(
      json.dumps(case['context'], ensure_ascii=False, indent=2), encoding='utf-8')
  (dst / 'chapter.md').write_text(
      (src / 'chapter.md').read_text(encoding='utf-8'), encoding='utf-8')
  print(f'exported to {dst}')
  "
  ```

  或者用 `jq` 只取 `context` 键:

  ```bash
  mkdir -p /tmp/annotate_export/ds_11_clean_setup
  jq '{context}' evals/dataset/cases/ds_11_clean_setup/case.json > /tmp/annotate_export/ds_11_clean_setup/context.json
  ```

  `jq` 版只导出了 `context.json`,`chapter.md` 需一并拷贝(否则标注者没有正文可读):

  ```bash
  cp evals/dataset/cases/ds_11_clean_setup/chapter.md /tmp/annotate_export/ds_11_clean_setup/
  ```

  把导出目录(只含 `context.json` 与 `chapter.md`)发给标注者,标注者全程只打开这个
  临时目录,不接触原始 `case.json`。

  **现在有更省事的办法:** `python -m evals.export_packets --out <目录>` 会把全部 case
  (或 `--split calibration` 只导某个 split)一键批量导出成上面这种无剧透标注包
  (每个 case 一个子目录,只含 `context.json` 四键 + `chapter.md`),不用再手写上面的
  一次性脚本或 `jq` 命令。
- `chapter.md` —— 本章正文,你要判读的对象。

## 标注流程

对每一个 case,按这个顺序做:

1. **读 context 四键**——先建立这一章「应该」是什么样:世界观规则是什么、人物的性格/立场/
   已知信息是什么、上一章末尾抛出了什么钩子、本章的写作目标是什么。
2. **读 chapter.md 正文**——完整读一遍,不要跳读。读的时候不下判断,先建立对情节的完整理解。
3. **打开 `rubric.md`,逐维核对**——`evals/dataset/rubric.md` 定义了 8 个维度,每维都有
   「定义 → 该抓(正例)→ 不该抓(反例)→ 边界例 → 严重度 → 证据要求」六节。对每一维:
   - 对照该维的「定义」「正例」「反例」,判断本章是否命中(`present: true/false`)。
   - 命中的话,按「严重度」一节的三档描述判 `severity`(高/中/低)。
   - 按「证据要求」一节写 `evidence`:大多数维度要求引本章正文里的原句(逐字复制,不要
     改写、不要省略号截断);「断钩子」「无爽点」是 absence 型缺陷(缺陷是"缺了什么"),
     引不出原文,这两维命中时 `evidence` 留空,把理由写进 `note`。
   - `note` 写清你的判断依据——具体违背了 context 里的哪一条、或者对照 rubric 哪一句
     正例/反例做的判断。

## 纪律(必须遵守)

- **只依据 rubric,不脑补。** 8 个维度的判据边界由 `rubric.md` 逐字定义,不要用你自己的
  写作品味、你觉得"这段写得不好"、或者 rubric 没提过的标准去抓硬伤。错别字、标点、纯文风
  问题不在这 8 维辖区内,别当硬伤记。
- **每例独立标注,不得对照他人结果。** 不要在标注过程中查看另一位标注者的 worksheet、
  也不要和另一位标注者讨论某个 case 该怎么判——这样做会让两份标注互相污染,κ 就测不出
  真实的人-人一致性。如果两位标注者需要对齐对 rubric 本身的理解,应该在正式标注开始前
  用别的 case(不进 calibration 计分的 case)讨论,而不是在标注过程中互相参考。
- **判读态度从严宁缺毋滥。** 继承 rubric 开篇的原则:两可情形一律判「未命中」(`present:
  false`),把假阳性压到最低。这不是让你消极摸鱼,而是和金标标注时用的是同一套标准,标注
  尺度不一致会直接反映在 κ 上。
- **拿不准时,按 rubric 的「边界例」一节判,并在 note 里记录。** 每个维度的 rubric 小节都有
  一个「边界例」,专门讨论"像但不是"或"是但不明显"的情况,并给出判断依据。遇到边界情况:
  1. 先去 rubric 对应维度的边界例小节找最接近的场景;
  2. 按边界例给出的判据下结论;
  3. 无论判成 present 还是 absent,都在 `note` 里写清楚"我参照了边界例的哪个说法、
     为什么这么判"——这个记录本身是有价值的数据,后续复核 rubric 覆盖度时会用到。

## 工作表怎么填

1. 复制一份模板:`evals/dataset/annotations/worksheet_template.json`。
2. 填 `case_id`(即目录名,如 `ds_03_hook`)、`annotator_id`(你的标识,建议用简短英文/
   拼音代号,如 `zhang01`)、`annotated_at`(标注完成时间,ISO 8601,如
   `"2026-07-20T15:00:00+08:00"`)。
3. `labels` 数组里的 8 条按 `evals/dataset.py` 里 `DIMENSIONS` 的顺序排列,**不要重排、
   不要增删**。对每一条,把 `present` 从 `null` 改成 `true`/`false`;命中时补
   `severity`(`"高"`/`"中"`/`"低"`)、`evidence`(原文子串,absence 型留 `null`)、
   `note`(判断依据);未命中时 `severity`/`evidence`/`note` 可以留 `null`,但鼓励在
   `note` 里简单写一句"为什么不算"(尤其是边界例情形)。
4. 存成 `annotations/<case_id>.<annotator_id>.json`,例如
   `annotations/ds_03_hook.zhang01.json`,放进 `evals/dataset/annotations/` 目录。

## 优先标哪些 case

`evals/dataset/cases/` 下每个 case 的 `case.json` 都有 `"split"` 字段,取值
`dev` / `calibration` / `holdout` 之一。**优先标 `calibration` split**——这是专门留出来
供人工与金标、以及两位标注者之间做一致性校准用的子集,Phase 3 的 κ 就是在这个 split 上算
的。当前 `calibration` split 下的 case 是:`ds_03_hook`、`ds_05_infoleak`、`ds_07_time`、
`ds_11_clean_setup`。标完 calibration 有余力,再考虑扩展到 `dev`/`holdout`。

**注意:case 目录名可能暗示缺陷类型**(如 `_hook`、`_time`、`_clean`),这是造数据时
留下的命名习惯,不是标注依据。判断只依据正文与 rubric,不要被目录名牵着走——尤其是
「像是设定干净就默认判 absent」这类由名字带出的先入之见。

## 完成之后

把你标好的 `annotations/<case_id>.<annotator_id>.json` 文件放进
`evals/dataset/annotations/` 目录即可。κ 计算脚本和结果汇总属于 Phase 3 的工作,不在本指南
范围内——你不需要自己算一致性,只需要交出独立、认真、依据 rubric 的判断。
