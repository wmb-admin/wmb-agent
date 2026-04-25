# Imported Skill Packs

这里记录当前项目已经接入的外部 GitHub Skill，以及推荐的使用方式。

## 已接入插件

### 1. `openai-frontend-suite`

- 来源: `openai/skills`
- 路由: `frontend`
- 包含:
  - `frontend-skill`
  - `playwright`
- 适合场景:
  - 页面视觉升级
  - 商业化落地页与中后台体验优化
  - 浏览器自动化验证、UI 流程回归、自测截图

### 2. `glebis-tdd`

- 来源: `glebis/claude-skills`
- 路由: `orchestrator`
- 包含:
  - `tdd`
- 适合场景:
  - 在真正写代码前先拆测试策略
  - 把需求拆成红灯/绿灯/重构步骤
  - 给前后端迭代增加测试驱动约束

### 3. `trailofbits-quality-suite`

- 来源: `trailofbits/skills`
- 路由: `ops`
- 包含:
  - `codeql`
  - `semgrep`
  - `sarif-parsing`
  - `sharp-edges`
  - `differential-review`
  - `supply-chain-risk-auditor`
  - `coverage-analysis`
  - `address-sanitizer`
  - 以及其他 fuzz / handbook 类技能
- 适合场景:
  - 静态分析
  - 代码审查补强
  - 供应链风险检查
  - 覆盖率与测试策略补强

### 4. `openai-ops-suite`

- 来源: `openai/skills`
- 路由: `ops`
- 包含:
  - `security-best-practices`
  - `gh-fix-ci`
  - `sentry`
- 适合场景:
  - 上线前安全检查
  - CI 失败排查
  - 异常监控与告警治理

## 推荐调用方式

### 前端设计 + 浏览器验证

```bash
PYTHONPATH=src python3 -m beauty_saas_agent.cli run \
  --version v1.0.1 \
  --workflow frontend_only \
  --task "重构会员充值页面的视觉层级并补浏览器回归检查" \
  --skills frontend-skill playwright
```

### 先做 TDD 拆解，再进入后端开发

```bash
PYTHONPATH=src python3 -m beauty_saas_agent.cli run \
  --version v1.0.1 \
  --workflow backend_only \
  --task "为储值卡充值接口补测试驱动的开发拆解" \
  --skills tdd BackendCodeWriteSkill BackendTestSkill
```

### 质量门禁 / 安全基线检查

```bash
PYTHONPATH=src python3 -m beauty_saas_agent.cli run \
  --version v1.0.1 \
  --workflow ops_only \
  --task "对本次迭代做安全与质量门禁检查" \
  --skills security-best-practices codeql semgrep gh-fix-ci sentry
```

### 供应链 / 覆盖率 / 评审补强

```bash
PYTHONPATH=src python3 -m beauty_saas_agent.cli run \
  --version v1.0.1 \
  --workflow ops_only \
  --task "评估依赖风险、覆盖率薄弱点和本次改动的评审重点" \
  --skills supply-chain-risk-auditor coverage-analysis differential-review sharp-edges
```

## 已固化为 workflow preset

这些组合已经写入项目级 workflow 配置文件 `.agent/workflow-presets.local.json`，可以直接通过 `--workflow` 调用：

- `frontend_enhanced`
- `frontend_visual_upgrade`
- `frontend_regression`
- `backend_tdd`
- `backend_api_tdd`
- `backend_change_review`
- `quality_audit`
- `release_guard`
- `pre_release_audit`

## 当前限制

- 这些外部 Skill 已经能参与运行时路由和 Prompt 构建。
- 但是否能真正执行到模型结果，还取决于你的本地模型服务是否可用。
- 你当前配置的 Ollama 地址是 `http://127.0.0.1:11434`，我本次验证时返回了连接拒绝。
