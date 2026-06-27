from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from loom import projects


class ProjectRegistryTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.config_home_patcher = patch("loom.config.Path.home", return_value=self.home)
        self.projects_home_patcher = patch("loom.projects.Path.home", return_value=self.home)
        self.config_home_patcher.start()
        self.projects_home_patcher.start()
        self.addCleanup(self.projects_home_patcher.stop)
        self.addCleanup(self.config_home_patcher.stop)

    def make_project(self, name="Book"):
        root = Path(self.tmp.name) / name
        root.mkdir()
        (root / "loom.toml").write_text("[backend]\nprovider = \"deepseek\"\n", encoding="utf-8")
        return root

    def test_empty_registry_has_default_shape(self):
        self.assertEqual(projects.registry_path(), self.home / ".loom" / "projects.json")
        data = projects.load_registry()
        self.assertEqual(data, {"default_dir": "", "projects": {}})

    def test_register_adds_project_and_marks_existing(self):
        root = self.make_project("Alpha")
        data = projects.register(root)
        entry = data["projects"]["Alpha"]
        self.assertEqual(Path(entry["path"]), root.resolve())
        self.assertTrue(entry["created"])
        self.assertTrue(entry["last_open"])
        self.assertTrue(entry["exists"])

        listed = projects.list_all()
        self.assertTrue(listed["projects"]["Alpha"]["exists"])

    def test_register_same_path_updates_last_open_without_duplicate(self):
        root = self.make_project("Alpha")
        with patch("loom.projects._now", side_effect=["2026-06-27T10:00:00", "2026-06-27T10:01:00"]):
            first = projects.register(root)
            second = projects.register(root)
        self.assertEqual(list(second["projects"]), ["Alpha"])
        self.assertEqual(second["projects"]["Alpha"]["created"], first["projects"]["Alpha"]["created"])
        self.assertEqual(second["projects"]["Alpha"]["created"], "2026-06-27T10:00:00")
        self.assertEqual(second["projects"]["Alpha"]["last_open"], "2026-06-27T10:01:00")

    def test_register_matches_existing_entry_with_equivalent_path_spelling(self):
        root = self.home / "Alpha"
        root.mkdir()
        projects.save_registry({
            "default_dir": "",
            "projects": {
                "Alpha": {
                    "path": str(root / ".." / "Alpha"),
                    "created": "2026-06-27T10:00:00",
                    "last_open": "2026-06-27T10:00:00",
                },
            },
        })

        with patch("loom.projects._now", return_value="2026-06-27T10:01:00"):
            data = projects.register(root.resolve())

        self.assertEqual(list(data["projects"]), ["Alpha"])
        self.assertEqual(data["projects"]["Alpha"]["created"], "2026-06-27T10:00:00")
        self.assertEqual(data["projects"]["Alpha"]["last_open"], "2026-06-27T10:01:00")

    def test_register_same_name_different_path_gets_suffix(self):
        root1 = self.make_project("Alpha")
        root2_parent = Path(self.tmp.name) / "other"
        root2 = root2_parent / "Alpha"
        root2.mkdir(parents=True)
        (root2 / "loom.toml").write_text("[backend]\nprovider = \"deepseek\"\n", encoding="utf-8")
        data = projects.register(root1)
        data = projects.register(root2)
        self.assertEqual(set(data["projects"]), {"Alpha", "Alpha (2)"})

    def test_invalid_json_falls_back_to_empty_registry(self):
        path = projects.registry_path()
        path.parent.mkdir(parents=True)
        path.write_text("{bad json", encoding="utf-8")
        self.assertEqual(projects.load_registry(), {"default_dir": "", "projects": {}})

    def test_non_utf8_registry_falls_back_to_empty_registry(self):
        path = projects.registry_path()
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xff\xfe\x00")
        self.assertEqual(projects.load_registry(), {"default_dir": "", "projects": {}})

    def test_save_registry_normalizes_data_before_persisting(self):
        root = self.make_project("Alpha")
        projects.save_registry({
            "default_dir": 123,
            "projects": {
                "Alpha": {
                    "path": str(root),
                    "created": "2026-06-27T10:00:00",
                    "last_open": "2026-06-27T10:01:00",
                    "extra": "ignored",
                },
                "Broken": "not a dict",
                "No path": {"created": "2026-06-27T10:00:00"},
                "Non-string timestamps": {
                    "path": str(root),
                    "created": 123,
                    "last_open": None,
                },
            },
        })

        self.assertEqual(projects.load_registry(), {
            "default_dir": "",
            "projects": {
                "Alpha": {
                    "path": str(root),
                    "created": "2026-06-27T10:00:00",
                    "last_open": "2026-06-27T10:01:00",
                },
                "Non-string timestamps": {
                    "path": str(root),
                    "created": "",
                    "last_open": "",
                },
            },
        })

    def test_remove_is_idempotent(self):
        root = self.make_project("Alpha")
        projects.register(root)
        self.assertTrue(projects.remove("Alpha"))
        self.assertFalse(projects.remove("Alpha"))
        self.assertEqual(projects.list_all()["projects"], {})

    def test_set_default_dir_expands_and_saves_path(self):
        root = self.make_project("Alpha")
        projects.register(root)
        default = Path(self.tmp.name) / "books"
        data = projects.set_default_dir(default)
        self.assertEqual(Path(data["default_dir"]), default.resolve())
        self.assertTrue(data["projects"]["Alpha"]["exists"])
        self.assertEqual(Path(projects.load_registry()["default_dir"]), default.resolve())
        self.assertEqual(Path(projects.get_default_dir()), default.resolve())
