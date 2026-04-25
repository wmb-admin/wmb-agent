# BackendCodeReadSkill

- 中文名称: 后端代码阅读
- 所属分组: （一）后端相关Skill
- 来源Prompt: 美业SaaS自动迭代智能体完整版Prompt
- 模板说明: 以下输入、输出、约束与交接项基于原始 Prompt 结构化整理，便于接入 Agent。

## 核心目标

只读取和理解后端代码，形成面向版本化开发的结构化上下文。

## 触发时机

- 开始新增或改造后端接口前
- 需要梳理 Controller、Service、Mapper、Entity、DTO、VO 关系时
- 需要确认接口版本、权限、字典和日志规范时

## 输入

- 当前迭代版本号
- 目标业务模块或接口范围
- 后端代码目录或模块路径
- 已有数据库表、实体或接口约定

## 输出

- 后端模块结构说明
- 接口版本与权限清单
- 数据表关系和业务流转摘要
- 供 BackendCodeWriteSkill 使用的上下文结论

## 硬性约束

- 只读取后端 Java 与配置文件，不读取前端代码
- 不得臆造接口、表结构或权限规则
- 必须确认接口前缀是否遵循 /api/vX/xxx

## 执行清单

1. 定位 Controller、Service、ServiceImpl、Mapper、Entity、DTO、VO、配置类
2. 识别统一返回体、异常体系、权限注解和日志结构
3. 梳理数据表主外键关系与业务流转
4. 记录缺失上下文、潜在风险和待确认点

## 交接对象

- BackendCodeWriteSkill
- BackendTestSkill

## 原始 Prompt

精准读取Java后端代码：Controller/Service/ServiceImpl/Mapper/Entity/DTO/VO/配置类
识别项目版本号、接口版本、权限体系、数据字典、业务逻辑、日志结构
梳理数据表关联关系、业务流转流程，绝不读取任何前端代码文件
