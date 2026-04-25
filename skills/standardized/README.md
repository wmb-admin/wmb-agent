# Standardized Skill Catalog

来源 Prompt: 美业SaaS自动迭代智能体完整版Prompt

说明: 输入、输出、约束、清单和交接对象为基于原始 Prompt 的结构化整理，方便后续接入本地 Agent。

## Skills

### BackendCodeReadSkill
- 中文名称: 后端代码阅读
- 所属分组: （一）后端相关Skill
- 核心目标: 只读取和理解后端代码，形成面向版本化开发的结构化上下文。
- 文件: `BackendCodeReadSkill.md`

### BackendCodeWriteSkill
- 中文名称: 后端代码开发
- 所属分组: （一）后端相关Skill
- 核心目标: 按照芋道规范实现后端版本化接口与业务逻辑。
- 文件: `BackendCodeWriteSkill.md`

### BackendTestSkill
- 中文名称: 后端一体化测试
- 所属分组: （一）后端相关Skill
- 核心目标: 对本次后端改动执行一体化测试、覆盖率统计并产出版本化报告。
- 文件: `BackendTestSkill.md`

### ApiDocSkill
- 中文名称: 版本化接口文档
- 所属分组: （一）后端相关Skill
- 核心目标: 在后端测试通过后生成版本绑定的接口文档，作为前端联调唯一依据。
- 文件: `ApiDocSkill.md`

### FrontendCodeReadSkill
- 中文名称: 前端代码阅读
- 所属分组: （二）前端相关Skill
- 核心目标: 只读取前端代码并理解页面、组件、接口封装、路由和权限体系。
- 文件: `FrontendCodeReadSkill.md`

### FrontendCodeWriteSkill
- 中文名称: 前端代码开发
- 所属分组: （二）前端相关Skill
- 核心目标: 严格基于版本化接口文档实现前端页面、API 请求层和联调逻辑。
- 文件: `FrontendCodeWriteSkill.md`

### FrontendUISkill
- 中文名称: 前端UI样式增强
- 所属分组: （二）前端相关Skill
- 核心目标: 在不破坏业务逻辑的前提下提升页面到商用级视觉质量。
- 文件: `FrontendUISkill.md`

### FrontendTestSkill
- 中文名称: 前端页面自测
- 所属分组: （二）前端相关Skill
- 核心目标: 执行前端页面全场景自测并维护迭代式操作说明。
- 文件: `FrontendTestSkill.md`

### DBStructSkill
- 中文名称: 数据库规范+慢SQL监控
- 所属分组: （三）数据库&监控Skill
- 核心目标: 审查数据库规范并输出慢 SQL 监控与优化建议。
- 文件: `DBStructSkill.md`

### MonitorSkill
- 中文名称: 全链路日志监控
- 所属分组: （三）数据库&监控Skill
- 核心目标: 收集前后端运行异常与请求失败情况，形成部署前阻断依据。
- 文件: `MonitorSkill.md`

### CodeRuleCheckSkill
- 中文名称: 代码规范检查
- 所属分组: （四）代码规范&部署Skill
- 核心目标: 检查代码健壮性、复用性和工程规范，排除上线前的实现风险。
- 文件: `CodeRuleCheckSkill.md`

### DevOpsSkill
- 中文名称: 版本化自动化部署
- 所属分组: （四）代码规范&部署Skill
- 核心目标: 执行版本化打包、部署、服务控制与回滚，输出最终交付结果。
- 文件: `DevOpsSkill.md`
