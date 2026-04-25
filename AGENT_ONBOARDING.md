# Agent Onboarding

这份文档的目标只有一个：让新的 agent 在最短时间内知道“先看哪里、从哪里改、怎么跑起来”。

## 先看什么

1. 先看 [README.md](/Users/wmb/IdeaProjects/myself/wmb-agent/README.md)
   了解项目用途、启动方式和当前能力边界。
2. 再看 [.agent/workspace-profile.local.json](/Users/wmb/IdeaProjects/myself/wmb-agent/.agent/workspace-profile.local.json)
   这里定义了后端仓库、前端仓库、工具链、服务地址和启动命令。
3. 最后按任务类型进入对应入口。

## 改这个项目自身时

### 前端页面入口

- [src/beauty_saas_agent/dashboard_assets/index.html](/Users/wmb/IdeaProjects/myself/wmb-agent/src/beauty_saas_agent/dashboard_assets/index.html)
  当前本地管理台是零构建单文件页面，所有 dashboard UI、交互逻辑、交流工作台都在这里。

### 后端接口入口

- [src/beauty_saas_agent/server.py](/Users/wmb/IdeaProjects/myself/wmb-agent/src/beauty_saas_agent/server.py)
  HTTP 服务入口，负责暴露 dashboard 和 `/api/v1/chat` 等接口。
- [src/beauty_saas_agent/prompt_builder.py](/Users/wmb/IdeaProjects/myself/wmb-agent/src/beauty_saas_agent/prompt_builder.py)
  任务执行主流程，包含 execution plan、workspace 执行、事件写入、最终响应拼装。
- [src/beauty_saas_agent/project_memory.py](/Users/wmb/IdeaProjects/myself/wmb-agent/src/beauty_saas_agent/project_memory.py)
  项目重点记忆层：负责记忆库初始化、召回排序、成功任务沉淀与去重。
- [src/beauty_saas_agent/task_store.py](/Users/wmb/IdeaProjects/myself/wmb-agent/src/beauty_saas_agent/task_store.py)
  任务快照、事件流、SQLite 汇总。
- [src/beauty_saas_agent/models.py](/Users/wmb/IdeaProjects/myself/wmb-agent/src/beauty_saas_agent/models.py)
  前后端通信用的数据结构定义。

### 配置与本地状态

- [src/beauty_saas_agent/config.py](/Users/wmb/IdeaProjects/myself/wmb-agent/src/beauty_saas_agent/config.py)
  环境变量和本地默认路径。
- [.agent/prompt-registry.local.json](/Users/wmb/IdeaProjects/myself/wmb-agent/.agent/prompt-registry.local.json)
  Prompt 注册表。
- [.agent/skill-plugins.local.json](/Users/wmb/IdeaProjects/myself/wmb-agent/.agent/skill-plugins.local.json)
  Skill 插件注册表。
- [.data/tasks](/Users/wmb/IdeaProjects/myself/wmb-agent/.data/tasks)
  历史任务快照和 SQLite 数据。
- 独立记忆库：`wmb_agent_memory`（MySQL）
  保存可复用流程记忆与实体记忆，不写入业务数据库。

## 改外部业务前后端仓库时

工作区已经把两个核心仓库映射好了：

- 后端仓库：`repos/luozuoServer`
- 前端仓库：`repos/luozuoWeb`

优先阅读顺序：

1. 查看 [.agent/workspace-profile.local.json](/Users/wmb/IdeaProjects/myself/wmb-agent/.agent/workspace-profile.local.json) 里的 `repos`、`services`、`notes`
2. 进入对应仓库看它自己的 `README*`
3. 再看实际入口文件

推荐入口：

- 若改后端业务服务，先从 `repos/luozuoServer` 的模块 `application.yaml`、`pom.xml`、控制器和服务入口开始
- 若改前端页面，先从 `repos/luozuoWeb/apps/web-ele` 的 `package.json`、`.env.development`、`vite.config.mts`、目标页面组件开始

## 常用启动与验证

### 本项目自身

```bash
PYTHONPATH=src python3 -m beauty_saas_agent.server
```

打开：

```text
http://127.0.0.1:8787/dashboard
```

模型模式切换（低负载 / 高质量）优先走控制台：

- `系统中心 -> 模型模式切换`
- 对应 API：`GET/POST /api/v1/model/mode`

### 前后端业务仓库

请优先参考 [.agent/workspace-profile.local.json](/Users/wmb/IdeaProjects/myself/wmb-agent/.agent/workspace-profile.local.json) 中已经维护好的：

- `build_commands`
- `test_commands`
- `start_commands`

## 给 agent 的最短指令模板

如果你想让新的 agent 更快进入状态，最省事的说法是：

```text
先看 README.md、AGENT_ONBOARDING.md 和 .agent/workspace-profile.local.json。
如果改本项目控制台，就从 src/beauty_saas_agent/dashboard_assets/index.html 和 server.py 开始；
如果改业务前后端，就按 workspace-profile 里的 repos 进入 luozuoServer / luozuoWeb。
```

## 当前约定

- 本项目控制台优先走“零构建单文件前端”，除非收益很高，否则不要轻易再引入新的前端工程。
- 任务反馈优先写入 task store，再由 dashboard 展示，不要只做临时前端状态。
- 重点知识优先沉淀到 Project Memory（独立库），不要把项目经验散落到临时对话里。
- 外部业务仓库的环境差异较大，先确认本地依赖、Nacos、数据库、Redis，再动服务启动逻辑。
