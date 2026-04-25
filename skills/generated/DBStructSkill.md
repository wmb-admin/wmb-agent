# DBStructSkill

- 中文名称: 数据库规范+慢SQL监控
- 所属分组: （三）数据库&监控Skill
- 来源Prompt: 美业SaaS自动迭代智能体完整版Prompt

## Skill Prompt

数据库规范：表名采用业务前缀+下划线命名，所有表强制包含id、create_time、update_time、deleted逻辑删除字段，字段注释完整、索引合理
通过ServBay监控慢SQL：抓取超时SQL、记录执行耗时、扫描行数，生成慢SQL分析报告，给出索引优化、SQL改写建议
慢SQL报告路径：/doc/db-slow-sql-{version}.md，未优化慢SQL禁止部署
仅做库表规范优化，不随意删改表/字段，不破坏现有业务数据
