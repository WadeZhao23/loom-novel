# 本地增强分支差异说明

本文说明当前分支 `codex/local-enhanced` 相对仓库
`y1240741780-design/loom-novel` 当前 `main` 的主要区别。

## 对比基准

- 目标仓库: `https://github.com/y1240741780-design/loom-novel.git`
- 目标仓库当前 `main`: `3f25ab9`
- 本地增强分支: `codex/local-enhanced`
- 本地增强分支提交: `521285c`
- Git 差异规模: 本地分支领先 `71` 个提交, 目标仓库领先 `0` 个提交
- 文件规模: `72 files changed, 12480 insertions(+), 86 deletions(-)`

## 总体定位变化

目标仓库当前版本主要是一个本地单项目 AI 小说写作工具:

```text
Web UI
  -> FastAPI 本地服务
  -> Agent 写作流水线
  -> 外置大脑 / 正文 / 项目文件
```

本地增强分支在此基础上扩展成了一个更完整的本地写作工作台:

```text
Web UI
  -> FastAPI 本地服务
     -> 写作流水线
     -> 项目库管理
     -> 章节规划服务
     -> TXT 导入任务系统
     -> 逆向解析流水线
     -> 全局/项目 Key 管理
  -> 项目目录 + 用户级配置 + 持久化导入任务
```

底层技术栈没有更换, 仍然是 Python + FastAPI + 静态单页 Web UI + 本地文件系统。
主要变化是应用边界变大: 从单项目写作工具, 扩展为多项目、可导入旧小说、可逆向生成设定资料的工作台。

## 主要新增能力

### 1. TXT 小说导入与逆向解析

新增文件:

- `loom/import_jobs.py`
- `loom/import_project.py`
- `loom/reverse_parse.py`
- `tests/test_import_jobs.py`
- `tests/test_import_api.py`
- `tests/test_import_project.py`
- `tests/test_reverse_parse.py`
- `tests/test_reverse_parse_pipeline.py`

新增能力:

- 上传 `.txt` 小说文件
- 自动识别章节边界
- 预览章节边界
- 手动拆分、合并、重排、编辑章节
- 选择章节范围
- 持久化导入任务
- 导入任务一直保留, 直到用户手动删除
- 支持运行中断后的恢复
- 支持按阶段断点恢复逆向解析
- 将解析结果物化为 Loom 项目
- 创建项目时由用户选择是否包含原文章节

### 2. 逆向解析流水线

原有方向是:

```text
外置大脑 -> Agent 写作流水线 -> 正文
```

增强分支新增反方向:

```text
TXT 正文 -> 章节列表 -> 世界观 / 修炼体系 / 人物 / 大纲 -> Loom 项目
```

这使项目可以从已有小说反推设定资料, 再进入 Loom 的正常写作流程。

### 3. 项目库管理

新增文件:

- `loom/projects.py`
- `tests/test_project_registry.py`

新增接口:

- `GET /api/projects`
- `POST /api/projects/register`
- `DELETE /api/projects/{name}`
- `PUT /api/projects/default-dir`

新增能力:

- 记录已创建或打开过的项目
- 欢迎页显示项目库
- 支持默认父目录
- 支持移除不存在或不需要的项目记录

### 4. 章节规划

新增文件:

- `loom/chapter_plan.py`
- `tests/test_chapter_plan.py`
- `tests/test_plan_endpoint.py`

新增接口:

- `POST /api/plan/generate`

新增能力:

- 批量生成章节细纲
- 支持设置总章数
- 支持从指定章节开始
- 支持跳过已有章节规划
- 支持强制重写已有规划
- 同步更新卡章纲

### 5. 全局 DeepSeek Key

主要修改:

- `loom/config.py`
- `loom/server.py`
- `loom/webui/app.js`
- `tests/test_global_deepseek_key.py`

原版本主要依赖项目 `.env` 或进程环境变量。
增强分支改为三层 Key 来源:

1. 进程环境变量
2. 项目 `.env`
3. 用户全局 `~/.loom/.env`

并且会避免切换项目时把上一个项目的 Key 泄漏到当前项目。

### 6. 前端工作台扩展

主要修改:

- `loom/webui/app.js`
- `loom/webui/index.html`
- `loom/webui/style.css`

新增界面:

- 项目库
- 导入小说入口
- 导入历史
- 章节边界预览
- 章节范围选择
- 逆向解析进度
- 解析结果编辑
- 创建项目模式选择
- 章节规划面板
- 全局 Key 保存入口

### 7. 上游 3.0.x 能力也已合入

增强分支同时合入了上游 `WadeZhao23/loom-novel` 后续版本能力, 包括:

- `3.0.1` 发布提交
- `3.0` 三通道: 立项卡 / 文风参考 / 参考范文播种
- 离线评测框架 `evals/`
- 文风相似度 grader
- 硬设定逐字透传相关改动
- 本地安全与缺陷修复

因此该分支不是只基于旧版做增强, 而是把上游新版能力和本地增强功能合在了一起。

## 依赖变化

`pyproject.toml` 新增:

```toml
python-multipart>=0.0.9
```

原因: FastAPI 处理 `.txt` 文件上传需要 multipart 表单解析能力。

## 重要文件变化概览

- `loom/server.py`: 增加项目库、全局 Key、章节规划、导入任务、逆向解析相关 API
- `loom/config.py`: 增加全局 Key、精确 dotenv 解析、Key 来源状态
- `loom/webui/app.js`: 扩展为多流程工作台
- `loom/import_jobs.py`: 导入任务持久化与状态管理
- `loom/reverse_parse.py`: TXT 分章与逆向解析核心逻辑
- `loom/import_project.py`: 将导入结果创建为 Loom 项目
- `loom/chapter_plan.py`: 批量章节规划服务
- `loom/projects.py`: 项目库注册表
- `evals/`: 上游评测框架

## 验证记录

合并完成后在本地执行过:

```text
python -m pytest -q -p no:cacheprovider
354 passed, 2 skipped, 1 warning

python -m compileall -q loom tests evals
通过

node --check loom/webui/app.js
通过

git diff --check
通过
```

其中 warning 是 FastAPI/TestClient 依赖栈里的 `StarletteDeprecationWarning`, 不影响测试结果。

## 未包含的本地未跟踪文件

当前工作区还有两个未跟踪文件, 没有放入本次分支提交:

- `docs/merge-plan.md`
- `uv.lock`

它们没有被纳入本说明文件对应的上传内容。
