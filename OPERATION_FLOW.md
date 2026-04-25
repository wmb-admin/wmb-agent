# Operation Flow

这份文档描述当前推荐的完整使用链路：

从启动依赖，到测试 Agent 连通性，再到发布任务、分工执行、测试验收和最终回看。

## 推荐主链路

1. 启动本地基础依赖

- 模型服务：Ollama 或 OpenAI 兼容接口
- 数据与中间件：MySQL、Redis、Nacos
- 需要联调业务仓库时，再启动 `luozuoServer` / `luozuoWeb`

2. 启动 Agent Runtime

```bash
PYTHONPATH=src python3 -m beauty_saas_agent.server
```

3. 打开控制台

```text
http://127.0.0.1:8787/dashboard
```

4. 先看“系统就绪度”

- Prompt 是否 active
- 仓库是否 ready
- Git 凭据是否可用
- 模型连通性是否通过
- 当前模型模式是否符合目标（开发建议 `dev`，复杂推理可切 `hq`）
- GitHub skills 是否已加载
- 项目记忆（Project Memory）是否可用

5. 再到“交流工作台”发任务

建议优先补这些字段：

- 本轮目标
- workflow
- execution_mode
- 目标仓库
- 补充上下文
- 期望产出

说明：

- 当前控制台默认按“异步提交任务 + 自动轮询进度”工作
- 任务发出后会先拿到 `task_id`
- 页面会持续刷新任务状态、最近事件和最终回复

补充：

- 模型模式切换入口：`系统中心 -> 模型模式切换`
- 切换 `dev/hq` 会即时更新运行时模型，新任务无需重启服务

6. Agent 执行后查看结果

- 本轮反馈概览
- 会话记录
- 最近任务
- 任务搜索 / 收藏
- 任务详情
- 最终回复
- Agent 步骤
- Handoff 交接
- 事件时间线
- 自动建议 / 文件时间线 / diff
- 自动验收报告
- 项目记忆命中与沉淀事件（`project_memory_recalled` / `project_memory_updated`）

7. 进入验收阶段

根据任务类型继续重跑：

- `status`：先看仓库和服务状态
- `start`：按 workspace-profile 中的 `start_commands` 启动项目
- `test`：优先跑后端/前端测试
- `validate`：做更完整的联调验证

补充：

- 如果任务文本本身明显包含“启动 / 拉起 / 运行前后端项目”等意图，运行时会优先自动推断为 `start`
- 如果任务属于可复用模式（例如“新增页面+联调+数据库配置”），系统会把成功经验写入独立记忆库，供后续任务自动召回

## workflow 推荐

### 前端页面开发 / 体验升级

- `frontend_visual_upgrade`
- `frontend_enhanced`

### 前端联调后回归

- `frontend_regression`

### 后端接口开发 / TDD

- `backend_tdd`
- `backend_api_tdd`

### 后端改动复核

- `backend_change_review`

### 质量审计

- `quality_audit`

### 上线前联查

- `pre_release_audit`
- `release_guard`

## 当前各 Agent 的职责

- `orchestrator`
  负责统一版本、任务拆解、路由和汇总
- `backend`
  负责后端分析、实现、测试、接口文档
- `frontend`
  负责前端分析、页面开发、UI 和回归
- `ops`
  负责数据库、规范、监控、发布守护

## 当前 GitHub 技能接入情况

目前已经真正注册并启用的 GitHub 插件有：

- `openai-frontend-suite`
  包含 `frontend-skill`、`playwright`
- `glebis-tdd`
  包含 `tdd`
- `trailofbits-quality-suite`
  包含 `coverage-analysis`、`differential-review`、`codeql`、`semgrep` 等
- `openai-ops-suite`
  包含 `gh-fix-ci`、`security-best-practices`、`sentry`

这些技能不只是“文件存在”，当前已经被 workflow 实际引用：

- `frontend_enhanced` / `frontend_regression` 使用 `frontend-skill`、`playwright`
- `backend_tdd` / `backend_api_tdd` 使用 `tdd`
- `backend_change_review` / `quality_audit` 使用 `coverage-analysis`、`differential-review`、`codeql`、`semgrep`
- `release_guard` / `pre_release_audit` 使用 `gh-fix-ci`、`security-best-practices`、`sentry`

## 当前流程已经顺的部分

- 已有明确工作台，可直接发任务和继续追问
- 已有 workflow 和 execution mode，能区分开发、测试、验证
- 已有任务事件流和快照，可回看执行过程
- 已有 GitHub 补强 skills，并且已经被 workflow 消费
- 已有验收相关技能：后端测试、前端测试、Playwright、覆盖率、静态分析、CI 守护
- 已有项目重点记忆：可把高价值流程和关联实体做增量沉淀，减少重复全量扫描

## 还可以继续优化的地方

- 支持流式输出，让长任务反馈更及时
- 支持会话分组、搜索和收藏
- 给 workflow 增加一键推荐入口，而不是手动挑选
- 增加“验收报告生成”能力，把测试、覆盖率、建议汇总成正式报告
- 增加真实浏览器录屏或截图归档，方便前端验收回放
