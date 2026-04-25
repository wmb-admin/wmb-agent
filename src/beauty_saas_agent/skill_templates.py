from __future__ import annotations

from typing import Dict, List

from .models import SkillDefinition, StandardSkillDefinition


# 标准技能库：把“原始技能文本”映射为结构化执行模板。
# 这部分主要用于技能导出与标准化展示，不直接改写运行时技能逻辑。
STANDARD_SKILL_LIBRARY: Dict[str, Dict[str, object]] = {
    "BackendCodeReadSkill": {
        "purpose": "只读取和理解后端代码，形成面向版本化开发的结构化上下文。",
        "when_to_use": [
            "开始新增或改造后端接口前",
            "需要梳理 Controller、Service、Mapper、Entity、DTO、VO 关系时",
            "需要确认接口版本、权限、字典和日志规范时",
        ],
        "inputs": [
            "当前迭代版本号",
            "目标业务模块或接口范围",
            "后端代码目录或模块路径",
            "已有数据库表、实体或接口约定",
        ],
        "outputs": [
            "后端模块结构说明",
            "接口版本与权限清单",
            "数据表关系和业务流转摘要",
            "供 BackendCodeWriteSkill 使用的上下文结论",
        ],
        "constraints": [
            "只读取后端 Java 与配置文件，不读取前端代码",
            "不得臆造接口、表结构或权限规则",
            "必须确认接口前缀是否遵循 /api/vX/xxx",
        ],
        "checklist": [
            "定位 Controller、Service、ServiceImpl、Mapper、Entity、DTO、VO、配置类",
            "识别统一返回体、异常体系、权限注解和日志结构",
            "梳理数据表主外键关系与业务流转",
            "记录缺失上下文、潜在风险和待确认点",
        ],
        "handoff_to": ["BackendCodeWriteSkill", "BackendTestSkill"],
    },
    "BackendCodeWriteSkill": {
        "purpose": "按照芋道规范实现后端版本化接口与业务逻辑。",
        "when_to_use": [
            "完成后端代码阅读并确认需求之后",
            "需要新增或修改后端接口、服务、校验和日志逻辑时",
        ],
        "inputs": [
            "BackendCodeReadSkill 的结构化阅读结果",
            "当前迭代版本号",
            "目标业务需求与接口范围",
            "数据库表结构、权限规则和返回体规范",
        ],
        "outputs": [
            "可编译的 Controller、Service、Mapper、DTO、VO 等后端代码",
            "带版本号的接口定义和请求路径说明",
            "校验、异常处理、统一返回与日志策略说明",
            "供 BackendTestSkill 和 ApiDocSkill 使用的接口信息",
        ],
        "constraints": [
            "仅开发后端逻辑，不编写前端代码",
            "所有接口必须携带版本号且与当前版本一致",
            "遵循分层、命名、注释、校验和日志规范",
            "后端测试未通过前不得进入接口文档和部署环节",
        ],
        "checklist": [
            "实现 Controller、Service、ServiceImpl、Mapper 和数据模型变更",
            "补齐参数校验、异常处理、统一返回体和标准日志",
            "确认权限、字典、事务和幂等处理是否完整",
            "在交付前整理接口清单供后续测试与文档使用",
        ],
        "handoff_to": ["BackendTestSkill", "ApiDocSkill"],
    },
    "BackendTestSkill": {
        "purpose": "对本次后端改动执行一体化测试、覆盖率统计并产出版本化报告。",
        "when_to_use": [
            "后端代码改动完成后",
            "需要确认接口稳定性、异常场景和覆盖率达标时",
        ],
        "inputs": [
            "本次迭代涉及的后端代码变更",
            "当前迭代版本号",
            "接口清单、权限要求和边界条件",
            "覆盖率门槛与豁免范围",
        ],
        "outputs": [
            "测试用例清单和执行结论",
            "覆盖率统计结果",
            "/target/site/test-report/backend/{version}/index.html",
            "未通过项、未覆盖代码和优化建议",
        ],
        "constraints": [
            "必须覆盖正常、非法参数、空参、权限不足、数据不存在、边界异常、重复提交场景",
            "最低行覆盖率不低于 80%",
            "Entity、DTO、VO、枚举、常量、简单 getter/setter、启动配置类可按规则豁免",
            "测试失败或覆盖率不达标时必须阻断后续流程",
        ],
        "checklist": [
            "为新增或修改接口设计全覆盖测试用例",
            "记录每条用例的场景、入参、期望、实际和结论",
            "执行 JaCoCo 覆盖率统计并整理未覆盖区域",
            "生成带版本号的 HTML 报告并输出阻断项",
        ],
        "handoff_to": ["ApiDocSkill"],
    },
    "ApiDocSkill": {
        "purpose": "在后端测试通过后生成版本绑定的接口文档，作为前端联调唯一依据。",
        "when_to_use": [
            "BackendTestSkill 全部通过之后",
            "前端准备接入或联调当前版本接口时",
        ],
        "inputs": [
            "当前迭代版本号",
            "后端接口实现与测试结果",
            "权限模型和角色区分规则",
            "请求入参与返回字段说明",
        ],
        "outputs": [
            "/doc/api-doc-{version}.html",
            "接口路径、方法、请求头、入参、出参、错误码、权限矩阵",
            "供 FrontendCodeWriteSkill 使用的联调依据",
        ],
        "constraints": [
            "只能在后端测试全部通过后生成",
            "文档必须与当前版本严格绑定",
            "必须区分系统总管理员、租户管理员、普通商家员工权限",
            "前端开发必须以该文档为准，不得自定义接口字段",
        ],
        "checklist": [
            "收集接口版本、地址、请求方式和请求头",
            "补齐字段说明、错误码和角色权限信息",
            "输出带版本号的 HTML 文档",
            "确认文档可作为前端唯一联调来源",
        ],
        "handoff_to": ["FrontendCodeWriteSkill"],
    },
    "FrontendCodeReadSkill": {
        "purpose": "只读取前端代码并理解页面、组件、接口封装、路由和权限体系。",
        "when_to_use": [
            "开始新增或改造前端页面前",
            "需要确认样式规范、组件复用和前端版本信息时",
        ],
        "inputs": [
            "当前迭代版本号",
            "目标页面或模块范围",
            "Vue3 页面、组件、API 封装和路由目录",
            "现有权限和全局配置",
        ],
        "outputs": [
            "前端页面结构与路由摘要",
            "接口调用方式与权限展示规则",
            "组件复用点与样式规范说明",
            "供 FrontendCodeWriteSkill 使用的上下文结论",
        ],
        "constraints": [
            "只读取前端代码，不读取后端 Java 文件",
            "不得臆造不存在的路由、组件或接口字段",
            "必须确认前端版本展示要求和风格约束",
        ],
        "checklist": [
            "定位页面、组件、API、路由、权限和全局配置文件",
            "识别页面布局、表单表格模式和组件复用规则",
            "梳理当前前端版本和样式规范",
            "整理后续开发需要的结构化上下文",
        ],
        "handoff_to": ["FrontendCodeWriteSkill", "FrontendUISkill"],
    },
    "FrontendCodeWriteSkill": {
        "purpose": "严格基于版本化接口文档实现前端页面、API 请求层和联调逻辑。",
        "when_to_use": [
            "接口文档已生成并确认版本号后",
            "需要开发或改造前端页面和接口对接逻辑时",
        ],
        "inputs": [
            "当前迭代版本号",
            "/doc/api-doc-{version}.html",
            "FrontendCodeReadSkill 的上下文结果",
            "页面需求、权限要求和错误码语义",
        ],
        "outputs": [
            "前端 API 请求层代码",
            "页面功能实现与权限展示逻辑",
            "底部前端版本号展示",
            "供 FrontendUISkill 和 FrontendTestSkill 使用的页面实现结果",
        ],
        "constraints": [
            "必须先读取对应版本接口文档再开发",
            "不得自定义接口、字段或错误码含义",
            "前后端版本必须完全一致",
            "字段名、请求方式、权限要求必须与接口文档一致",
        ],
        "checklist": [
            "核对接口版本、路径、方法、权限和校验规则",
            "生成对应版本的前端 API 调用层",
            "实现页面逻辑并完成字段映射",
            "在页面底部展示前端版本号并确认联调一致性",
        ],
        "handoff_to": ["FrontendUISkill", "FrontendTestSkill"],
    },
    "FrontendUISkill": {
        "purpose": "在不破坏业务逻辑的前提下提升页面到商用级视觉质量。",
        "when_to_use": [
            "页面功能开发完成后",
            "需要统一全站视觉风格、间距、层级和状态样式时",
        ],
        "inputs": [
            "已完成功能开发的页面与组件",
            "现有设计风格和品牌约束",
            "需要增强的按钮、表单、表格、卡片、空态与加载态",
        ],
        "outputs": [
            "优化后的页面样式实现",
            "统一的视觉风格说明",
            "供 FrontendTestSkill 验证的样式增强结果",
        ],
        "constraints": [
            "只做样式增强，不改变页面业务逻辑",
            "不破坏既有布局结构和交互流程",
            "需兼顾页面间距、对齐、留白、层级、阴影和过渡表现",
        ],
        "checklist": [
            "统一页面间距、栅格、留白和层级",
            "优化按钮、表单、表格、卡片和状态样式",
            "补足加载态、空态和过渡动效",
            "确认增强结果不影响业务行为",
        ],
        "handoff_to": ["FrontendTestSkill"],
    },
    "FrontendTestSkill": {
        "purpose": "执行前端页面全场景自测并维护迭代式操作说明。",
        "when_to_use": [
            "前端页面与样式开发完成后",
            "准备进入监控、规范检查和部署前",
        ],
        "inputs": [
            "本次前端页面与交互改动",
            "当前迭代版本号",
            "角色权限、页面操作路径和接口请求信息",
            "/doc/frontend-operation.md 的现有内容",
        ],
        "outputs": [
            "前端自测用例与执行结论",
            "/target/site/test-report/frontend/{version}/index.html",
            "更新后的 /doc/frontend-operation.md",
            "问题清单和优化建议",
        ],
        "constraints": [
            "必须覆盖页面渲染、交互操作、权限展示、输入校验、接口请求和样式适配",
            "每条用例必须包含页面、步骤、期望、实际和结论",
            "自测不通过时必须阻断后续流程",
            "每次迭代都必须同步完善前端操作说明",
        ],
        "checklist": [
            "设计并执行覆盖核心页面场景的自测用例",
            "记录页面、步骤、期望、实际和测试结论",
            "更新操作说明中的角色流程、功能说明和注意事项",
            "生成带版本号的 HTML 自测报告并输出问题项",
        ],
        "handoff_to": ["MonitorSkill", "CodeRuleCheckSkill"],
    },
    "DBStructSkill": {
        "purpose": "审查数据库规范并输出慢 SQL 监控与优化建议。",
        "when_to_use": [
            "每次迭代开始时建立数据库基线",
            "涉及新表、索引、查询性能或慢 SQL 风险时",
        ],
        "inputs": [
            "当前迭代版本号",
            "目标业务模块的数据表和 SQL",
            "数据库命名规范、字段规范和索引要求",
            "ServBay 的慢 SQL 监控数据",
        ],
        "outputs": [
            "库表规范检查结果",
            "慢 SQL 列表、耗时、扫描行数与优化建议",
            "/doc/db-slow-sql-{version}.md",
            "供后端开发和部署前确认的数据库基线",
        ],
        "constraints": [
            "表名需遵循业务前缀加下划线命名",
            "不得随意删改表和字段，不破坏现有业务数据",
            "未处理的慢 SQL 问题禁止部署",
            "字段注释、逻辑删除字段和索引设计必须合理",
        ],
        "checklist": [
            "检查表名、主键、时间字段、逻辑删除字段和注释规范",
            "抓取慢 SQL 并记录耗时与扫描行数",
            "给出索引优化或 SQL 改写建议",
            "输出带版本号的慢 SQL 分析报告",
        ],
        "handoff_to": ["BackendCodeWriteSkill", "DevOpsSkill"],
    },
    "MonitorSkill": {
        "purpose": "收集前后端运行异常与请求失败情况，形成部署前阻断依据。",
        "when_to_use": [
            "前后端改动完成并可运行后",
            "需要确认日志、控制台和网络层是否存在严重异常时",
        ],
        "inputs": [
            "当前迭代版本号",
            "后端服务日志和接口调用记录",
            "前端控制台报错、网络请求失败和资源加载情况",
            "ServBay 或其他运行监控信息",
        ],
        "outputs": [
            "/doc/monitor-{version}.md",
            "后端异常、前端报错、失败接口和时间线记录",
            "严重异常阻断项与修复建议",
        ],
        "constraints": [
            "必须记录异常信息、发生接口、时间和版本",
            "前端需覆盖控制台报错、4xx/5xx、资源加载失败等问题",
            "出现严重异常时必须阻断部署流程",
        ],
        "checklist": [
            "抓取后端 ERROR、空指针、SQL、参数和权限异常",
            "监控前端控制台、网络请求和资源加载失败",
            "整理异常发生页面、操作链路和版本信息",
            "生成监控报告并标记是否允许部署",
        ],
        "handoff_to": ["CodeRuleCheckSkill", "DevOpsSkill"],
    },
    "CodeRuleCheckSkill": {
        "purpose": "检查代码健壮性、复用性和工程规范，排除上线前的实现风险。",
        "when_to_use": [
            "功能开发、自测和监控完成后",
            "准备进入打包和部署前",
        ],
        "inputs": [
            "本次前后端改动代码",
            "团队代码规范和复用要求",
            "日志、异常、组件封装和公共方法抽取情况",
        ],
        "outputs": [
            "代码规范检查结果",
            "待修复问题清单和建议",
            "是否允许进入 DevOpsSkill 的结论",
        ],
        "constraints": [
            "只检查健壮性和规范性，不替代业务验收",
            "后端要关注注解、工具类、异常和日志规范",
            "前端要关注组件封装、命名规范和重复代码",
            "检查不通过时必须先修复再重检",
        ],
        "checklist": [
            "审查后端注解、异常处理、日志和通用工具使用",
            "审查前端组件复用、命名、公共方法抽取和冗余代码",
            "整理规范问题与修复建议",
            "确认阻断项关闭后再允许进入部署环节",
        ],
        "handoff_to": ["DevOpsSkill"],
    },
    "DevOpsSkill": {
        "purpose": "执行版本化打包、部署、服务控制与回滚，输出最终交付结果。",
        "when_to_use": [
            "所有前置环节均通过后",
            "需要执行版本发布、重启或回滚时",
        ],
        "inputs": [
            "当前迭代版本号",
            "代码规范检查通过结论",
            "后端打包与前端构建产物",
            "servbay-cli 或等价部署控制命令",
        ],
        "outputs": [
            "带版本号的 Git 提交信息或发布记录",
            "部署、重启、状态检查和回滚结果",
            "最终版本信息、文档路径和部署反馈汇总",
        ],
        "constraints": [
            "所有前置测试、监控、规范检查通过前不得部署",
            "部署动作必须与当前版本号绑定",
            "必须支持按版本回滚并反馈服务状态",
            "若存在未修复慢 SQL 或严重异常则禁止发布",
        ],
        "checklist": [
            "执行版本化 Git 提交与构建打包",
            "停止、部署、启动或重启目标服务",
            "检查服务状态并验证是否需要回滚",
            "汇总版本信息、文档路径和部署结果给用户",
        ],
        "handoff_to": ["IterationSummary"],
    },
}


def _as_list(value: object) -> List[str]:
    """把任意值安全转为字符串列表。"""
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def build_standard_skill_definition(skill: SkillDefinition, source_title: str) -> StandardSkillDefinition:
    """把原始 SkillDefinition 转成标准化定义。"""
    metadata = STANDARD_SKILL_LIBRARY.get(skill.name, {})
    return StandardSkillDefinition(
        name=skill.name,
        title=skill.title,
        group=skill.group,
        purpose=str(metadata.get("purpose", "基于原始 Prompt 的能力定义执行对应职责。")),
        when_to_use=_as_list(metadata.get("when_to_use")),
        inputs=_as_list(metadata.get("inputs")),
        outputs=_as_list(metadata.get("outputs")),
        constraints=_as_list(metadata.get("constraints")),
        checklist=_as_list(metadata.get("checklist")),
        handoff_to=_as_list(metadata.get("handoff_to")),
        source_prompt=source_title,
        raw_prompt=skill.content,
    )
