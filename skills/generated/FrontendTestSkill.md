# FrontendTestSkill

- 中文名称: 前端页面自测
- 所属分组: （二）前端相关Skill
- 来源Prompt: 美业SaaS自动迭代智能体完整版Prompt

## Skill Prompt

设计前端全场景测试用例，必含：页面渲染、交互操作、权限展示、输入校验、接口请求、样式适配场景
单条用例包含：测试页面、操作步骤、期望结果、实际结果、测试结论
维护迭代式前端总操作说明，路径：/doc/frontend-operation.md，每次迭代同步更新，完善各角色操作流程、功能说明、注意事项
生成带版本号的HTML自测报告，路径：/target/site/test-report/frontend/{version}/index.html
报告包含：版本信息、测试概览、用例详情、操作说明更新摘要、问题优化建议
自测不通过，终止后续流程，返回修复后重测
