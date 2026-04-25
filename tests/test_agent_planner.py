from __future__ import annotations

import unittest

from beauty_saas_agent.agent_planner import build_execution_plan, resolve_agents


class AgentPlannerTestCase(unittest.TestCase):
    def test_resolve_agents_defaults_to_orchestrator(self) -> None:
        self.assertEqual(resolve_agents(None, [], []), ["orchestrator"])

    def test_build_execution_plan_uses_workflow_and_skill_owners(self) -> None:
        plan = build_execution_plan(
            workflow="full_iteration",
            requested_agents=[],
            resolved_skills=[
                "BackendCodeWriteSkill",
                "FrontendCodeWriteSkill",
                "DevOpsSkill",
            ],
            explicit_skills=[
                "BackendCodeWriteSkill",
                "FrontendCodeWriteSkill",
                "DevOpsSkill",
            ],
        )

        self.assertEqual(plan.agents, ["orchestrator", "backend", "frontend", "ops"])
        self.assertEqual(plan.skill_map["backend"], ["BackendCodeWriteSkill"])
        self.assertEqual(plan.skill_map["frontend"], ["FrontendCodeWriteSkill"])
        self.assertEqual(plan.skill_map["ops"], ["DevOpsSkill"])
        self.assertEqual(plan.steps[0].handoff_to, "backend")
        self.assertEqual(plan.steps[-1].handoff_to, None)

    def test_bug_fix_workflow_defaults_to_orchestrator(self) -> None:
        plan = build_execution_plan(
            workflow="bug_fix",
            requested_agents=[],
            resolved_skills=[],
            explicit_skills=[],
        )
        self.assertEqual(plan.agents, ["orchestrator", "bug_inspector"])

    def test_backend_workflow_does_not_pull_ops_from_workflow_skill_preset(self) -> None:
        plan = build_execution_plan(
            workflow="backend_only",
            requested_agents=[],
            resolved_skills=[
                "DBStructSkill",
                "BackendCodeReadSkill",
                "BackendCodeWriteSkill",
                "BackendTestSkill",
                "ApiDocSkill",
                "CodeRuleCheckSkill",
            ],
            explicit_skills=[],
        )

        self.assertEqual(plan.agents, ["orchestrator", "backend"])

    def test_external_skill_owner_override_routes_to_frontend(self) -> None:
        plan = build_execution_plan(
            workflow=None,
            requested_agents=[],
            resolved_skills=["frontend-prototyper"],
            explicit_skills=["frontend-prototyper"],
            skill_owner_overrides={"frontend-prototyper": "frontend"},
        )

        self.assertEqual(plan.agents, ["orchestrator", "frontend"])
        self.assertEqual(plan.skill_map["frontend"], ["frontend-prototyper"])

    def test_unknown_skill_falls_back_to_orchestrator(self) -> None:
        plan = build_execution_plan(
            workflow=None,
            requested_agents=[],
            resolved_skills=["unknown-skill"],
            explicit_skills=["unknown-skill"],
        )

        self.assertEqual(plan.agents, ["orchestrator"])
        self.assertEqual(plan.skill_map["orchestrator"], ["unknown-skill"])


if __name__ == "__main__":
    unittest.main()
