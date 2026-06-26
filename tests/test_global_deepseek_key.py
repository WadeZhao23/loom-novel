import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loom import config


def write_project(root: Path, env_text: str = "") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "loom.toml").write_text(
        "\n".join(
            [
                "[backend]",
                'provider = "deepseek"',
                'model = "deepseek-chat"',
                "",
                "[novel]",
                'title = "测试书"',
                '"章节字数" = 800',
                "",
                "[gate]",
                '"轮数" = 1',
                "",
            ]
        ),
        encoding="utf-8",
    )
    if env_text:
        (root / ".env").write_text(env_text, encoding="utf-8")


class GlobalDeepSeekKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_env = os.environ.get("DEEPSEEK_API_KEY")
        os.environ.pop("DEEPSEEK_API_KEY", None)
        if hasattr(config, "_APPLIED_DEEPSEEK_KEY"):
            config._APPLIED_DEEPSEEK_KEY = None

    def tearDown(self) -> None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
        if self.old_env is not None:
            os.environ["DEEPSEEK_API_KEY"] = self.old_env
        if hasattr(config, "_APPLIED_DEEPSEEK_KEY"):
            config._APPLIED_DEEPSEEK_KEY = None

    def test_global_key_is_used_when_project_has_no_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project)
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")

                key, source = config.resolve_deepseek_key(project)

            self.assertEqual(key, "sk-global")
            self.assertEqual(source, "global")

    def test_project_key_overrides_global_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")

                key, source = config.resolve_deepseek_key(project)

            self.assertEqual(key, "sk-project")
            self.assertEqual(source, "project")

    def test_process_key_overrides_project_and_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")
            os.environ["DEEPSEEK_API_KEY"] = "sk-process"
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")

                key, source = config.resolve_deepseek_key(project)

            self.assertEqual(key, "sk-process")
            self.assertEqual(source, "process")

    def test_load_config_replaces_loom_applied_key_when_switching_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            first = base / "first"
            second = base / "second"
            write_project(first, "DEEPSEEK_API_KEY=sk-first\n")
            write_project(second, "DEEPSEEK_API_KEY=sk-second\n")
            with mock.patch.object(config.Path, "home", return_value=home):
                config.load_config(first)
                self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), "sk-first")

                config.load_config(second)

            self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), "sk-second")

    def test_load_config_removes_stale_loom_applied_key_when_next_project_has_no_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            first = base / "first"
            second = base / "second"
            write_project(first, "DEEPSEEK_API_KEY=sk-first\n")
            write_project(second)
            with mock.patch.object(config.Path, "home", return_value=home):
                config.load_config(first)
                self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), "sk-first")

                config.load_config(second)

            self.assertIsNone(os.environ.get("DEEPSEEK_API_KEY"))

    def test_set_global_env_key_creates_global_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")
                env_path = home / ".loom" / ".env"

            self.assertEqual(env_path.read_text(encoding="utf-8"), "DEEPSEEK_API_KEY=sk-global\n")

    def test_key_status_does_not_return_raw_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")

            status = config.key_status(project)

            self.assertEqual(status["source"], "project")
            self.assertTrue(status["effective"])
            self.assertTrue(status["project"])
            self.assertFalse(status["global"])
            self.assertNotIn("key", status)
            self.assertNotIn("api_key", status)
            self.assertNotIn("sk-project", repr(status))


if __name__ == "__main__":
    unittest.main()
