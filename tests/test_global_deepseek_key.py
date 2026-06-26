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
        self.old_owner = os.environ.get("_LOOM_DEEPSEEK_KEY_OWNER")
        os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ.pop("_LOOM_DEEPSEEK_KEY_OWNER", None)
        if hasattr(config, "_APPLIED_DEEPSEEK_KEY"):
            config._APPLIED_DEEPSEEK_KEY = None

    def tearDown(self) -> None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ.pop("_LOOM_DEEPSEEK_KEY_OWNER", None)
        if self.old_env is not None:
            os.environ["DEEPSEEK_API_KEY"] = self.old_env
        if self.old_owner is not None:
            os.environ["_LOOM_DEEPSEEK_KEY_OWNER"] = self.old_owner
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

    def test_matching_real_process_key_is_not_cleared_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            first = base / "first"
            second = base / "second"
            write_project(first, "DEEPSEEK_API_KEY=sk-same\n")
            write_project(second)
            with mock.patch.object(config.Path, "home", return_value=home):
                config.load_config(first)
                self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), "sk-same")

                # Simulate the process owning the same value Loom injected earlier.
                os.environ["DEEPSEEK_API_KEY"] = "sk-same"
                os.environ.pop("_LOOM_DEEPSEEK_KEY_OWNER", None)

                config.load_config(second)

            self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), "sk-same")

    def test_set_global_env_key_creates_global_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            with mock.patch.object(config.Path, "home", return_value=home):
                config.set_global_env_key("sk-global")
                env_path = home / ".loom" / ".env"

            self.assertEqual(env_path.read_text(encoding="utf-8"), "DEEPSEEK_API_KEY=sk-global\n")

    def test_key_status_does_not_return_raw_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")
            with mock.patch.object(config.Path, "home", return_value=home):
                status = config.key_status(project)

            self.assertEqual(status["source"], "project")
            self.assertTrue(status["effective"])
            self.assertTrue(status["project"])
            self.assertFalse(status["global"])
            self.assertNotIn("key", status)
            self.assertNotIn("api_key", status)
            self.assertNotIn("sk-project", repr(status))

    def test_key_status_does_not_mutate_owner_marker_for_process_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")
            os.environ["DEEPSEEK_API_KEY"] = "sk-process"
            os.environ["_LOOM_DEEPSEEK_KEY_OWNER"] = "1"
            config._APPLIED_DEEPSEEK_KEY = "sk-other"
            with mock.patch.object(config.Path, "home", return_value=home):
                status = config.key_status(project)

            self.assertEqual(os.environ.get("_LOOM_DEEPSEEK_KEY_OWNER"), "1")
            self.assertEqual(status["source"], "process")
            self.assertTrue(status["effective"])
            self.assertTrue(status["process"])
            self.assertTrue(status["project"])

    def test_set_project_env_key_replaces_only_exact_deepseek_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            write_project(
                project,
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY_OLD=keep-old",
                        "OTHER=value",
                        "DEEPSEEK_API_KEY=replace-me",
                        "DEEPSEEK_API_KEY_BACKUP=keep-backup",
                        "",
                    ]
                ),
            )

            config.set_project_env_key(project, "sk-new")

            env_text = (project / ".env").read_text(encoding="utf-8")
            self.assertIn("DEEPSEEK_API_KEY_OLD=keep-old", env_text)
            self.assertIn("OTHER=value", env_text)
            self.assertIn("DEEPSEEK_API_KEY_BACKUP=keep-backup", env_text)
            self.assertIn("DEEPSEEK_API_KEY=sk-new", env_text)
            self.assertNotIn("DEEPSEEK_API_KEY=replace-me", env_text)

    def test_set_project_env_key_replaces_spaced_and_exported_deepseek_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            write_project(
                project,
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY = old",
                        "export DEEPSEEK_API_KEY = exported-old",
                        "DEEPSEEK_API_KEY_OLD=keep-me",
                        "OTHER=value",
                        "",
                    ]
                ),
            )

            config.set_project_env_key(project, "sk-new")

            env_text = (project / ".env").read_text(encoding="utf-8")
            self.assertEqual(env_text.count("DEEPSEEK_API_KEY=sk-new"), 1)
            self.assertIn("DEEPSEEK_API_KEY_OLD=keep-me", env_text)
            self.assertIn("OTHER=value", env_text)
            self.assertNotIn("DEEPSEEK_API_KEY = old", env_text)
            self.assertNotIn("export DEEPSEEK_API_KEY = exported-old", env_text)

    def test_server_state_includes_key_status_without_raw_key(self) -> None:
        from loom import server

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            write_project(project, "DEEPSEEK_API_KEY=sk-project\n")
            (project / "正文").mkdir()

            state = server._state(project)

            self.assertTrue(state["backend"]["key_set"])
            self.assertEqual(state["backend"]["key_status"]["source"], "project")
            self.assertNotIn("sk-project", repr(state))

    def test_global_key_endpoint_saves_key_and_returns_state(self) -> None:
        from loom import server

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "book"
            write_project(project)
            with mock.patch.object(config.Path, "home", return_value=home):
                body = server.GlobalKeyBody(root=str(project), api_key="sk-global")

                state = server.update_global_key(body)

            self.assertTrue((home / ".loom" / ".env").is_file())
            self.assertTrue(state["backend"]["key_set"])
            self.assertEqual(state["backend"]["key_status"]["source"], "global")
            self.assertNotIn("sk-global", repr(state))

    def test_global_key_endpoint_rejects_empty_key(self) -> None:
        from loom import server

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            write_project(project)
            body = server.GlobalKeyBody(root=str(project), api_key="   ")

            response = server.update_global_key(body)

            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
