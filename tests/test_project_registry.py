from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from loom import projects
from loom.server import app


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

    def client(self):
        return TestClient(app, base_url="http://127.0.0.1")

    def client_without_server_exceptions(self):
        return TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)

    def test_open_project_registers_valid_project(self):
        root = self.make_project("OpenMe")

        response = self.client().post("/api/project/open", json={"root": str(root)})

        self.assertEqual(response.status_code, 200, response.text)
        data = self.client().get("/api/projects").json()
        self.assertEqual(Path(data["projects"]["OpenMe"]["path"]), root.resolve())
        self.assertTrue(data["projects"]["OpenMe"]["exists"])

    def test_register_rejects_non_project_folder(self):
        folder = Path(self.tmp.name) / "NotAProject"
        folder.mkdir()

        response = self.client().post("/api/projects/register", json={"root": str(folder)})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertEqual(projects.list_all()["projects"], {})

    def test_delete_project_is_idempotent_and_returns_updated_list(self):
        root = self.make_project("Alpha")
        projects.register(root)

        first = self.client().delete("/api/projects/Alpha")
        second = self.client().delete("/api/projects/Alpha")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["projects"], {})
        self.assertEqual(second.json()["projects"], {})

    def test_default_dir_endpoint_updates_and_returns_resolved_path(self):
        default = Path(self.tmp.name) / "books"

        response = self.client().put("/api/projects/default-dir", json={"path": str(default)})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(Path(response.json()["default_dir"]), default.resolve())
        self.assertEqual(Path(projects.get_default_dir()), default.resolve())

    def test_create_project_registers_project_and_parent_as_default_dir(self):
        parent = Path(self.tmp.name) / "created"
        parent.mkdir()

        response = self.client().post(
            "/api/project/create",
            json={"name": "CreatedBook", "parent": str(parent), "genre": None},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = projects.list_all()
        self.assertEqual(Path(data["default_dir"]), parent.resolve())
        self.assertEqual(Path(data["projects"]["CreatedBook"]["path"]), (parent / "CreatedBook").resolve())
        self.assertTrue(data["projects"]["CreatedBook"]["exists"])

    def test_create_project_does_not_register_when_state_cannot_load(self):
        parent = Path(self.tmp.name) / "created"
        parent.mkdir()

        with patch("loom.server._state", side_effect=ValueError("broken state")):
            response = self.client_without_server_exceptions().post(
                "/api/project/create",
                json={"name": "BrokenBook", "parent": str(parent), "genre": None},
            )

        self.assertEqual(projects.list_all()["projects"], {})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json(), {"error": "broken state"})

    def test_sample_open_registers_sample_and_parent_as_default_dir(self):
        parent = Path(self.tmp.name) / "samples"
        parent.mkdir()

        response = self.client().post("/api/sample/open", json={"parent": str(parent)})

        self.assertEqual(response.status_code, 200, response.text)
        data = self.client().get("/api/projects").json()
        self.assertEqual(Path(data["default_dir"]), parent.resolve())
        self.assertEqual(len(data["projects"]), 1)
        entry = next(iter(data["projects"].values()))
        self.assertTrue(Path(entry["path"]).is_relative_to(parent.resolve()))
        self.assertTrue(entry["exists"])

    def test_sample_open_does_not_register_existing_invalid_sample_folder(self):
        from loom.scaffold import open_sample

        probe_parent = Path(self.tmp.name) / "probe"
        probe_parent.mkdir()
        sample_name = open_sample(probe_parent).name
        parent = Path(self.tmp.name) / "samples"
        parent.mkdir()
        (parent / sample_name).mkdir()

        response = self.client_without_server_exceptions().post("/api/sample/open", json={"parent": str(parent)})

        self.assertEqual(projects.list_all()["projects"], {})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("error", response.json())
