from __future__ import annotations

import unittest

from beauty_saas_agent.execution_diagnostics import analyze_command_output


class ExecutionDiagnosticsTestCase(unittest.TestCase):
    def test_analyze_pytest_failure_extracts_failed_target(self) -> None:
        diagnostic = analyze_command_output(
            command="pytest tests/test_demo.py -q",
            stdout="FAILED tests/test_demo.py::test_create_user - AssertionError\n\n================ short test summary info =================\nFAILED tests/test_demo.py::test_create_user - AssertionError: boom\n",
            stderr="",
        )

        self.assertEqual(diagnostic.failure_kind, "pytest")
        self.assertEqual(diagnostic.title, "测试执行失败")
        self.assertIn("tests/test_demo.py::test_create_user", diagnostic.failed_targets)
        self.assertIn("AssertionError", diagnostic.primary_error)
        self.assertTrue(diagnostic.locations)
        self.assertEqual(diagnostic.locations[0].path, "tests/test_demo.py")

    def test_analyze_typescript_failure_extracts_location(self) -> None:
        diagnostic = analyze_command_output(
            command="pnpm check:type",
            stdout="",
            stderr="src/views/user/index.ts:12:5 - error TS2339: Property 'age' does not exist on type 'User'.\n",
        )

        self.assertEqual(diagnostic.failure_kind, "typescript")
        self.assertEqual(diagnostic.title, "TypeScript 类型检查失败")
        self.assertIn("src/views/user/index.ts:12:5", diagnostic.primary_error)
        self.assertIn("TS2339", diagnostic.primary_error)
        self.assertTrue(diagnostic.locations)
        self.assertEqual(diagnostic.locations[0].line, 12)

    def test_analyze_maven_compile_failure_extracts_error(self) -> None:
        diagnostic = analyze_command_output(
            command="mvn test",
            stdout="",
            stderr="[ERROR] COMPILATION ERROR : \n[ERROR] /tmp/demo/UserService.java:[17,20] cannot find symbol\n",
        )

        self.assertEqual(diagnostic.failure_kind, "maven-compile")
        self.assertEqual(diagnostic.title, "Maven 编译失败")
        self.assertIn("cannot find symbol", diagnostic.primary_error)
        self.assertTrue(diagnostic.locations)
        self.assertEqual(diagnostic.locations[0].path, "/tmp/demo/UserService.java")

    def test_analyze_spring_boot_main_class_failure(self) -> None:
        diagnostic = analyze_command_output(
            command="mvn -pl luozuo-gateway -am spring-boot:run",
            stdout="",
            stderr="[ERROR] Failed to execute goal org.springframework.boot:spring-boot-maven-plugin:3.5.13:run (default-cli) on project luozuo: Unable to find a suitable main class, please add a 'mainClass' property -> [Help 1]\n",
        )

        self.assertEqual(diagnostic.failure_kind, "spring-boot-main-class")
        self.assertEqual(diagnostic.title, "Spring Boot 启动入口识别失败")
        self.assertIn("main class", diagnostic.primary_error.lower())
        self.assertIn("luozuo", diagnostic.failed_targets)

    def test_timeout_primary_error_prefers_timeout_reason(self) -> None:
        diagnostic = analyze_command_output(
            command="mvn -f gateway/pom.xml org.springframework.boot:spring-boot-maven-plugin:3.5.13:run",
            stdout="[INFO] Scanning for projects...\n",
            stderr="",
            reason="Command timed out after 1800 seconds.",
        )

        self.assertEqual(diagnostic.failure_kind, "timeout")
        self.assertIn("timed out", diagnostic.primary_error.lower())
        self.assertNotEqual(diagnostic.primary_error, "[INFO] Scanning for projects...")

    def test_non_command_timeout_text_does_not_override_compile_failure(self) -> None:
        diagnostic = analyze_command_output(
            command="mvn test",
            stdout="",
            stderr="[ERROR] COMPILATION ERROR : \n[ERROR] /tmp/demo/UserService.java:[17,20] cannot find symbol\nCaused by: connect timed out\n",
        )

        self.assertEqual(diagnostic.failure_kind, "maven-compile")
        self.assertIn("cannot find symbol", diagnostic.primary_error)


if __name__ == "__main__":
    unittest.main()
