import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "forge/spec.py"


class ProfileTests(unittest.TestCase):
    def load(self, directory, content=None, explicit=None, context=None):
        if content is not None:
            (Path(directory) / "forge-profile.toml").write_text(content)
        env = {"FORGEAI3D_HOME": directory} if context is None else dict(context)
        if explicit is not None:
            env["FORGEAI3D_PROFILE"] = explicit
        with patch.dict(os.environ, env, clear=True):
            spec = importlib.util.spec_from_file_location("profile_fixture", SOURCE)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module

    def test_external_profile_changes_defaults_without_runtime_writes(self):
        before = SOURCE.read_bytes()
        with tempfile.TemporaryDirectory() as td:
            profile = self.load(td, 'available=["PETG"]\n[printer]\nname="Fixture"\nbed=[200,210,220]\nextrusion_width=0.6\nhardened_nozzle=true\n[materials.PETG.clearances]\nslip=0.42\n')
            self.assertEqual(profile.wall(3), 1.8)
            self.assertEqual(profile.clearance("PETG", "slip"), 0.42)
            self.assertEqual(profile.A1_MINI.bed, (200, 210, 220))
            self.assertFalse(profile.in_stock("PLA"))
            self.assertEqual(profile.supported("PLA-CF"), [])
        self.assertEqual(SOURCE.read_bytes(), before)

    def test_absent_profile_keeps_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self.load(td).wall(3), 1.26)

    def test_invalid_profiles_fail_instead_of_silent_fallback(self):
        for text in ['[printer]\nnozzle=0', '[printer]\nbed=[1,2]', '[printer]\nenclosed="yes"', '[printer]\nunknown=1', 'available=["UNKNOWN"]', '[materials.PETG]\nshrink=1.0', '[materials.UNKNOWN]\nshrink=0.1', '[materials.PETG]\nname="PETG spool"']:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                with self.assertRaises(ValueError):
                    self.load(td, text)

    def test_explicit_missing_profile_fails(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(FileNotFoundError):
            self.load(td, explicit=str(Path(td) / "missing.toml"))

    def test_profile_in_current_or_explicit_model_folder(self):
        for mode in ["cwd", "model"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
                context = {} if mode == "cwd" else {"FORGEAI3D_MODEL_DIR": td}
                cwd = Path(td if mode == "cwd" else other)
                with patch.object(Path, "cwd", return_value=cwd):
                    profile = self.load(td, "[printer]\nextrusion_width=0.6\n", context=context)
                self.assertEqual(profile.wall(3), 1.8)

    def test_shared_workspace_profile_and_explicit_file_precedence(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as model:
            (Path(workspace) / "forge-profile.toml").write_text("[printer]\nextrusion_width=0.5\n")
            (Path(model) / "forge-profile.toml").write_text("[printer]\nextrusion_width=0.6\n")
            context = {"FORGEAI3D_HOME": workspace, "FORGEAI3D_MODEL_DIR": model}
            self.assertEqual(self.load(model, context=context).wall(3), 1.5)
            explicit = str(Path(model) / "forge-profile.toml")
            self.assertEqual(self.load(model, explicit=explicit, context=context).wall(3), 1.8)
