from __future__ import annotations

import unittest

from beauty_saas_agent.project_memory import (
    build_page_change_checklist,
    extract_keywords,
    extract_table_names,
)


class ProjectMemoryTestCase(unittest.TestCase):
    def test_extract_table_names_from_sql_text(self) -> None:
        text = """
        ALTER TABLE sys_user ADD COLUMN mobile VARCHAR(32);
        select * from crm_customer where id = 1;
        INSERT INTO bpm_task_log(id, status) values (1, 'ok');
        """
        tables = extract_table_names(text)
        self.assertIn("sys_user", tables)
        self.assertIn("crm_customer", tables)
        self.assertIn("bpm_task_log", tables)

    def test_extract_keywords_contains_domain_terms(self) -> None:
        text = "新增页面后需要联调后端接口、菜单权限和数据库配置"
        keywords = extract_keywords(text)
        self.assertIn("页面", keywords)
        self.assertIn("联调", keywords)
        self.assertIn("数据库", keywords)

    def test_build_page_change_checklist_includes_data_and_permissions(self) -> None:
        checklist = build_page_change_checklist(
            repos=["backend", "frontend"],
            tables=["sys_user", "crm_customer"],
        )
        content = "\n".join(checklist)
        self.assertIn("菜单", content)
        self.assertIn("权限", content)
        self.assertIn("配置", content)
        self.assertIn("sys_user", content)


if __name__ == "__main__":
    unittest.main()

