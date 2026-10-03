"""Verify ignore rules without creating sensitive files."""

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GitignoreTests(unittest.TestCase):
    def test_sensitive_paths_are_ignored(self):
        for path in (
            ".env", ".env.local", "config/.env.production", "private.pem",
            "config/private.key", "credentials.json", "secrets.json",
            "secrets/token.txt",
        ):
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT,
                    check=False,
                )
                self.assertEqual(result.returncode, 0)

    def test_project_files_are_not_ignored(self):
        for path in ("AGENTS.md", ".gitignore", "tests/test_gitignore.py"):
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
