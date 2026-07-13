# 领航员在场形态:起书居中 · 平时悬浮 · IP 形象 —— 设计

2026-07-13 · 用户拍板(提灯引路人意象 + A/B 并行);经四路调研(布局读仓/行业模式联网实证/IP 形象/交互状态机)收敛。

## 0. 一句话

删掉侧栏 journey-card;**同一份问答卡渲染函数按状态画进两个容器**——未解锁写第一章时画进主编辑区正中(领航员占画面核心;该区域现为空 textarea+「选左边一个文件来看/改」死文案),解锁后缩成右下 48px 头像悬浮球(静默、随叫随到)。IP 形象=与五工序同风格的水墨「提灯引路人」头像,放进 `webui/agents/navigator.jpg` 零代码生效。

## 1. 依据(调研要点)

- **行业**:无一家把起书引导放侧栏(Sudowrite Story Engine=主画布分步表单);侧栏助手让用户觉得"它不知道我在看什么"(NN/g)。Clippy 教训:被注视→焦虑↑绩效↓,dismiss 不被记住=礼仪第一大罪;药方="不被召唤时收成不打扰的图标"(Stanford)。Duo 成立公式=出现节奏:onboarding 占核心、日常退场、心流闭嘴。中文作者敏感点在"替我写"不在形象(阅文/番茄争议),话术永远"陪跑打杂"。
- **工程**:三态判定零后端新增(`writing_unlocked`/`has_body`/`chapters.length`/`missing` 已全暴露);豁免逻辑白送保证——第一章一织出居中态永不再劫持画面;`paintJourney` 全量重建无内部状态,容器参数化即可复用;右下角是全页唯一空角(toast 底中/织章条底中/专注退出右上)。

## 2. 状态机(六态,前端纯推导、无第二真相)

```js
function navMode() {
  if (!DATA) return "hidden";
  if (_weaving) return "hidden";                                   // S4 织章中
  if (DATA.writing_unlocked === false)
    return _navYield ? "float" : "center";                         // S0 新书起书 / S1 导入回补
  return "float";                                                  // S2 刚解锁 / S3 正常 / S5 写后
}
```

| 态 | 判定 | 形态与行为 |
|---|---|---|
| S0 新书起书 | `!writing_unlocked && !has_body` | **主区居中大卡**(in-flow 空态内容,非 overlay):头像 64px+「领航员 · 陪你把地基打完」+「距开写还差 N 项」+横向段进度(点=goto)+问题卡(复用 jc-* DOM)+footer「✨AI 铺底稿」ghost+「先自己逛逛」 |
| S1 导入回补 | `!writing_unlocked && has_body` | 同 S0;引导语换「先读正文提炼」;「✨从正文提炼设定」升 primary(原侧栏入口搬来) |
| S2 刚解锁 | `writing_unlocked && chapters.length===0` | 一次性交接动效:居中卡 160ms 淡出→球淡入+pulse-gold 一圈(localStorage once 键);popover 自动开一次「地基齐了——去织第一章。我搬去右下角,随叫随到」;btn-write-next pulse 一次 |
| S3 正常写作 | `writing_unlocked && chapters.length>0` | 右下 48px 头像球,**静默**;未读=一枚 6px `--seal` 朱点(不数数):①末章 edited&&!learned ②voice 未做且指纹 default ③豁免书 missing>0 弱提示;点开=锚定 popover(复用 _placeBubble):段进度+回头改+问答就地进行(不回居中);`body.focus-mode`/`body.typing` 下隐藏 |
| S4 织章中 | 前端 `_weaving` | 领航员**隐身**(织章有 run-strip,两个 AI 在场感不同屏;顺手规避织章中答题撞写锁) |
| S5 写后引导 | chapter_done 后 | 现 `maybeCoachLearnLoop` 气泡挂领航员头像(话术归人设);之后只亮未读点 |

**转移表**:进书/refresh 纯推导(T1);答题致解锁→S2 交接一次(T2);居中「让位」=点侧栏文件或「先自己逛逛」→会话级 `_navYield=true` 暂退球、**不落 localStorage**,下次进书回居中(T3);写下一章/⌘↵/球内「继续答题」/409 → 回居中并聚焦(T4);writeChapter/closeRun 翻转 `_weaving`(T5/T6)。新增前端态仅 `_weaving`、`_navYield` 两个会话变量 + 一个交接 once 键。

## 3. 语义修正(随形态一并定死)

- **dismiss(×)整个废弃**:居中态是主内容不可关(只可让位);球无 × 需求;`loom_journey_dismiss:<root>` 键四处读写全删(不再读即迁移完成,防老键值把球藏掉)。
- **门禁弹层退役**:`openGateGuide` 函数壳保留、内部改转发 `enterNavCenter(missing)`(清 `_navYield`→切居中→卡顶「还差 N 项」1s 高亮,不 shake);写前软拦与 409 分支两个调用点签名不动;guide-overlay 本体保留给 skills/外置大脑空态等其它用途。
- **主区让位规则**(唯一新交互决策):居中态占据 editor-pane 的空态位;用户 openFile 后编辑器回归、领航员自动让位成球;关书/删光章回起点态照 navMode 重推。
- **未接模型**:居中卡体=「先接入模型,伙伴才能出题」+接入按钮(现逻辑搬容器)。
- **动效克制**:答题/跳段仅卡体 120-160ms 淡入+4px 上移;唯一"大"动效是 S0→S2 交接(功能性方位教学,一次性),不做 FLIP 飞行;吉祥物动画/表情包仍在 Avoid。

## 4. IP 形象(A 轨,已拍板「提灯引路人」)

- 与五工序同风格:白描淡彩水墨、512×512 JPEG ≤60KB、宣纸留白、**全图唯一一点朱砂红=灯焰**。温和浅笑年轻引路人,墨衫白描,手提墨线小灯笼——"照路不代步"。
- 生成:ModelScope Qwen-Image 直连(MCP 下载 bug 走 urllib;负向提示反成吸引子→全正向锁色);6 张候选(3 措辞×2 seed)圆裁三档小尺寸预览挑一张;**提示词+seed 留档 docs/design/proposals/**(补上五工序断掉的复现链)。
- **不做大立绘**:头像放大+CSS 纸墨装饰(淡墨题头线/宣纸卡/小朱印)——立绘违纸墨克制且多尺寸一致性难保。
- 接入零代码:`AGENTS_META` 已配 navigator slug,文件放进 `webui/agents/` 即全站生效。

## 5. 改动面(B 轨)

| 文件 | 改动 |
|---|---|
| index.html | 删 :76 journey-card;editor-pane 内加 `#nav-center`;body 末加 `#nav-ball`+`#nav-popover` |
| app.js | `paintJourney` 容器参数化(`journeyHost()`);新增 `navMode()/enterNavCenter()`;`renderJourney` 按 navMode 分发+控制 editor/球显隐;`openGateGuide` 改转发;`writeChapter/closeRun` 各加 `_weaving` 翻转;删 4 处 dismiss 键读写;`maybeCoachLearnLoop` 挂头像;三 POST 换书守卫延续 |
| style.css | `#nav-center`(列布局+纸面卡+横向段进度征用 .journey-strip 族)、`#nav-ball`(fixed 右下 48px+朱点)、popover(复用 coach-pop 族)、focus/typing 隐藏、两条过渡;顺手把 .jc-opt/.jc-btn 的硬编码灰换 `var(--line)` 系 token |
| 资产 | `webui/agents/navigator.jpg`(A 轨产出) |

**后端零改动,391+ 后端测试不动**;前端验证=node --check + preview 六态冒烟(钉 loom_root 测试书)。

## 6. 风险与已知处置

- render 全量重画蹦浮层→开合状态放模块级变量、enterProject 清零;
- 老用户 localStorage 存量 dismiss=1→不再读该键即无害;
- 双帧闪烁(加载中…→内容)在大卡会放大→JOURNEY 有缓存时直接 paint、后台静默刷新;
- 样例书导览(tour)不锚 journey-card 不炸,但首见引导文案与球对齐;
- 二期插槽向前兼容:章前决策卡=写前从球弹 popover;织章中视图=S4 从「隐身」升级为「球出勤只播状态」,枚举不改。

## 7. 分期

- **A · IP 形象**(并行进行中):6 候选→用户挑→入库+留档。
- **B · 状态机改造**(SDD,5-6 任务):宿主与 CSS → paintJourney 参数化+navMode 分发 → 门禁转发+dismiss 废弃+织章隐身 → 交接动效+未读点+popover → 写后气泡挂头像+文案 → 文档收口(教程/CONTEXT/spec 留档)。
- **C · 收尾**:样例导览对齐、教程截图区文字更新。

## 8. 刻意不做(Avoid)

- 大立绘/吉祥物动画/表情包/加载动效(纸墨克制,spec 既有 Avoid 延续);
- 领航员主动弹话打断写作(占核心只在空状态;心流中彻底闭嘴;主动开口只用安静的未读点);
- 后端加字段(三态判定现有字段穷举);dismiss 永久键(病根已由搬家治掉);
- "替你写"话术(中文作者敏感神经;姿态永远=陪跑打杂/照路不代步)。

---
一期实现备注(2026-07-13 终审留档):spec §2 三处一期裁剪——S1 专属引导语与「从正文提炼设定」primary 位、S0 footer「✨AI 铺底稿」ghost 入口、S2 交接的 btn-write-next pulse 与居中卡 160ms 淡出(现瞬时切换)。归下轮打磨;Esc 关 popover 同。
