import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.target = Path(self.workspace.name) / "skills"

    def test_silly_installs_aep_and_relative_dependency_resolves(self):
        result = installer.install("codex", self.target, ["silly"])
        self.assertEqual(result["skills"], ["aep", "silly"])
        self.assertTrue((self.target / "silly/../aep/SKILL.md").resolve().is_file())
        self.assertIn("allow_implicit_invocation: false", (self.target / "aep/agents/openai.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("disable-model-invocation", (self.target / "aep/SKILL.md").read_text(encoding="utf-8"))

    def test_claude_adapter_preserves_explicit_aep_and_automatic_silly(self):
        installer.install("claude", self.target)
        self.assertIn("disable-model-invocation: true", (self.target / "aep/SKILL.md").read_text(encoding="utf-8"))
        self.assertNotIn("disable-model-invocation", (self.target / "silly/SKILL.md").read_text(encoding="utf-8"))

    def test_aep_can_be_installed_alone(self):
        installer.install("codex", self.target, ["aep"])
        self.assertTrue((self.target / "aep/SKILL.md").is_file())
        self.assertFalse((self.target / "silly").exists())

    def test_dry_run_creates_nothing(self):
        result = installer.install("codex", self.target, ["silly"], dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.target.exists())

    def test_existing_skill_is_preserved_without_replace(self):
        (self.target / "aep").mkdir(parents=True)
        note = self.target / "aep/user-note.md"
        note.write_text("local changes", encoding="utf-8")
        with self.assertRaises(ValueError):
            installer.install("codex", self.target)
        self.assertEqual(note.read_text(encoding="utf-8"), "local changes")
        self.assertFalse((self.target / "silly").exists())

    def test_replace_keeps_backup_outside_skill_discovery(self):
        installer.install("codex", self.target)
        original = self.target / "aep/user-note.md"
        original.write_text("preserve me", encoding="utf-8")
        result = installer.install("codex", self.target, replace=True)
        backup = Path(result["backup"])
        self.assertFalse(backup.is_relative_to(self.target))
        self.assertEqual((backup / "aep/user-note.md").read_text(encoding="utf-8"), "preserve me")
        self.assertFalse(original.exists())

    def test_failed_pair_update_restores_both_existing_skills(self):
        installer.install("codex", self.target)
        for name in ("aep", "silly"):
            (self.target / name / "user-note.md").write_text(name, encoding="utf-8")
        real_move = installer.shutil.move
        calls = 0

        def interrupted_move(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated interruption")
            return real_move(source, destination)

        with patch.object(installer.shutil, "move", side_effect=interrupted_move):
            with self.assertRaises(OSError):
                installer.install("codex", self.target, replace=True)
        for name in ("aep", "silly"):
            self.assertEqual((self.target / name / "user-note.md").read_text(encoding="utf-8"), name)
        self.assertFalse(list(self.target.parent.glob(".be-smart-stage-*")))

    def test_repository_target_is_rejected(self):
        with self.assertRaises(ValueError):
            installer.install("codex", ROOT / "installed", dry_run=True)

    def test_unknown_skill_is_rejected(self):
        with self.assertRaises(ValueError):
            installer.install("codex", self.target, ["unknown"], dry_run=True)
        self.assertFalse(self.target.exists())

    def test_dependency_cycle_is_rejected(self):
        circular = {"aep": {"dependencies": ["silly"]}, "silly": {"dependencies": ["aep"]}}
        with patch.object(installer.json, "loads", return_value=circular):
            with self.assertRaisesRegex(ValueError, "cycle"):
                installer.selection(["silly"])


if __name__ == "__main__":
    unittest.main()
