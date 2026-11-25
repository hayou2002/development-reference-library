#!/usr/bin/env python3
"""Offline tests for the development reference library."""

from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import references  # noqa: E402


class CatalogValidationTests(unittest.TestCase):
    def setUp(self):
        self.payload = copy.deepcopy(references.load_catalog())

    def test_shipped_catalog_is_valid(self):
        self.assertEqual(references.validate_catalog(self.payload), [])
        self.assertEqual(self.payload["schema_version"], 1)
        self.assertEqual(len(self.payload["categories"]), 12)
        self.assertGreaterEqual(len(self.payload["entries"]), 15)

    def test_reports_missing_required_field(self):
        del self.payload["entries"][0]["tasks"]
        errors = references.validate_catalog(self.payload)
        self.assertTrue(any("缺少 tasks" in error for error in errors), errors)

    def test_reports_duplicate_id(self):
        self.payload["entries"].append(copy.deepcopy(self.payload["entries"][0]))
        errors = references.validate_catalog(self.payload)
        self.assertTrue(any("重复 id" in error for error in errors), errors)

    def test_reports_unknown_category(self):
        self.payload["entries"][0]["categories"].append("nope")
        errors = references.validate_catalog(self.payload)
        self.assertTrue(any("未知分类" in error for error in errors), errors)

    def test_reports_invalid_status_kind_and_date(self):
        entry = self.payload["entries"][0]
        entry["status"] = "done"
        entry["kind"] = "website"
        entry["last_verified"] = "2026-13-40"
        errors = references.validate_catalog(self.payload)
        joined = " ".join(errors)
        self.assertIn("status", joined)
        self.assertIn("kind", joined)
        self.assertIn("last_verified", joined)

    def test_reports_invalid_homepage(self):
        self.payload["entries"][0]["homepage"] = "http://example.com/x y"
        errors = references.validate_catalog(self.payload)
        self.assertTrue(any("homepage" in error for error in errors), errors)

    def test_reports_evidence_without_source(self):
        self.payload["entries"][0]["evidence"] = ["听说可用"]
        errors = references.validate_catalog(self.payload)
        self.assertTrue(any("evidence" in error for error in errors), errors)

    def test_rejects_secret_like_values(self):
        self.payload["entries"][0]["setup"] = "使用 sk_live_abcdefgh12345678 调用"
        errors = references.validate_catalog(self.payload)
        self.assertTrue(any("疑似包含密钥" in error for error in errors), errors)

    def test_category_count_is_enforced(self):
        self.payload["categories"].pop()
        errors = references.validate_catalog(self.payload)
        self.assertTrue(any("12 类" in error for error in errors), errors)


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = references.load_catalog()

    def ids(self, query, **kwargs):
        result = references.search(self.payload, query, kwargs.get("category", []), kwargs.get("kind", []), kwargs.get("limit", 5))
        return [entry["id"] for entry in result["results"]]

    def test_supabase_database_permissions(self):
        result = references.search(self.payload, "Supabase 数据库权限", [], [], 3)
        self.assertEqual(result["results"][0]["id"], "supabase-skills-mcp")
        self.assertIn("RLS", " ".join(result["results"][0]["tasks"]))

    def test_nextjs_deployment(self):
        result = references.search(self.payload, "Next.js 部署", [], [], 3)
        self.assertEqual(result["results"][0]["id"], "vercel-skills-mcp")

    def test_browser_testing(self):
        result = references.search(self.payload, "网页浏览器测试", [], [], 3)
        self.assertEqual(result["results"][0]["id"], "playwright-mcp")

    def test_expanded_framework_mobile_auth_and_repository_sources(self):
        cases = {
            "Next.js 运行时错误": "nextjs-mcp",
            "跨端 App 构建": "expo-mcp",
            "微信小程序预览上传": "wechat-miniprogram",
            "Clerk 登录认证": "clerk-mcp",
            "公开仓库文档 MCP": "gitmcp",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertIn(expected, self.ids(query))

    def test_continuous_chinese_input(self):
        result = references.search(self.payload, "数据库权限", [], [], 3)
        self.assertIn("supabase-skills-mcp", [entry["id"] for entry in result["results"]])

    def test_category_filter_accepts_id_and_chinese_name(self):
        by_id = references.search(self.payload, "数据库", ["backend-data"], [], 5)
        by_name = references.search(self.payload, "数据库", ["后端数据"], [], 5)
        self.assertTrue(by_id["results"])
        self.assertEqual([e["id"] for e in by_id["results"]], [e["id"] for e in by_name["results"]])
        for entry in by_id["results"]:
            self.assertIn("backend-data", entry["categories"])

    def test_kind_filter(self):
        result = references.search(self.payload, "文档", [], ["mcp"], 5)
        self.assertTrue(result["results"])
        self.assertTrue(all(entry["kind"] == "mcp" for entry in result["results"]))

    def test_limit_is_respected(self):
        wide = references.search(self.payload, "数据库", [], [], 5)
        narrow = references.search(self.payload, "数据库", [], [], 1)
        self.assertGreaterEqual(wide["count"], 2)
        self.assertEqual(narrow["returned"], 1)
        self.assertEqual(len(narrow["results"]), 1)
        self.assertEqual(narrow["results"][0]["id"], wide["results"][0]["id"])

    def test_no_result_does_not_fabricate(self):
        result = references.search(self.payload, "量子纠缠香蕉", [], [], 3)
        self.assertEqual(result["results"], [])
        self.assertEqual(result["count"], 0)
        self.assertIn("没有匹配条目", result["note"])

    def test_unknown_filter_raises(self):
        with self.assertRaises(ValueError):
            references.search(self.payload, "数据库", ["不存在的分类"], [], 3)
        with self.assertRaises(ValueError):
            references.search(self.payload, "数据库", [], ["plugin"], 3)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = references.main(argv)
        return code, buffer.getvalue()

    def test_check_passes(self):
        code, output = self.run_cli(["check"])
        self.assertEqual(code, 0)
        self.assertIn("校验通过", output)

    def test_check_json(self):
        code, output = self.run_cli(["check", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(output)
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["entries"], len(references.load_catalog()["entries"]))

    def test_search_json_contract(self):
        code, output = self.run_cli(["search", "Supabase 数据库权限", "--json", "--limit", "2"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["query"], "Supabase 数据库权限")
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["results"][0]["id"], "supabase-skills-mcp")
        for field in ("access", "setup", "cost", "license", "status", "last_verified", "evidence"):
            self.assertIn(field, payload["results"][0])

    def test_search_rejects_bad_limit(self):
        code, _ = self.run_cli(["search", "数据库", "--limit", "9"])
        self.assertEqual(code, 2)

    def test_search_empty_query_is_rejected(self):
        code, _ = self.run_cli(["search", "   "])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
