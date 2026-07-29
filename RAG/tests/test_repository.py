from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

RAG_ROOT = Path(__file__).resolve().parents[1]
LOCAL_PACKAGES = {"eval", "golden", "jobrag", "webapp"}


def _module_target(parts: list[str]) -> tuple[Path, Path]:
    base = RAG_ROOT.joinpath(*parts)
    return base.with_suffix(".py"), base / "__init__.py"


class RepositoryValidationTest(unittest.TestCase):
    def test_committed_json_files_are_valid(self):
        for path in RAG_ROOT.rglob("*.json"):
            with self.subTest(path=path.relative_to(RAG_ROOT)):
                json.loads(path.read_text(encoding="utf-8"))

    def test_local_absolute_imports_resolve(self):
        for path in RAG_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                    continue
                parts = node.module.split(".")
                if parts[0] not in LOCAL_PACKAGES:
                    continue
                module_file, package_init = _module_target(parts)
                with self.subTest(path=path.relative_to(RAG_ROOT), module=node.module):
                    self.assertTrue(
                        module_file.is_file() or package_init.is_file(),
                        f"local module does not exist: {node.module}",
                    )
                if package_init.is_file():
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        child_file, child_init = _module_target(parts + [alias.name])
                        with self.subTest(
                            path=path.relative_to(RAG_ROOT),
                            imported=f"{node.module}.{alias.name}",
                        ):
                            self.assertTrue(
                                child_file.is_file() or child_init.is_file(),
                                f"local package member does not exist: {node.module}.{alias.name}",
                            )

    def test_webapp_reads_v4_report(self):
        server = (RAG_ROOT / "webapp" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("from eval import harness", server)
        self.assertIn("from eval.run import", server)

    def test_personal_claude_settings_are_ignored(self):
        ignored = (RAG_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".claude/settings.local.json", ignored)
        self.assertFalse((RAG_ROOT / ".claude" / "settings.local.json").exists())


if __name__ == "__main__":
    unittest.main()
