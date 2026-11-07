"""Private bundle paths, relocation and export regression checks."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from build123d import Box
from forge import io


class ModelLayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cwd = Path.cwd()
        os.chdir(self.home)
        self.addCleanup(os.chdir, self.cwd)

    def test_workspace_default_and_ignore(self):
        subprocess.run(['git', 'init', '-q', str(self.home)], check=True)
        folder = io.model_dir('part')
        self.assertEqual(folder, self.home / 'models/part')
        source = folder / 'model.py'
        source.touch()
        subprocess.run(['git', 'check-ignore', '-q', str(source)], check=True)
        self.assertEqual(io.prints_dir(), self.home / 'models')
        self.assertEqual(io.root(), self.home)

    def test_opened_bundle_and_local_cache(self):
        (self.home / 'model.py').touch()
        self.assertEqual(io.model_dir('part'), self.home)
        io.save_spec('Fixture', {'length': 2.0}, 'test fixture')
        self.assertEqual(io.get_spec('fixture')['dimensions'], {'length': 2.0})
        self.assertTrue((self.home / 'extras/specs_cache.json').is_file())
        self.assertFalse((self.home / 'models').exists())

    def test_explicit_relocated_bundle(self):
        folder = self.home / 'elsewhere/part'
        os.environ['FORGEAI3D_MODEL_DIR'] = str(folder)
        self.assertEqual(io.model_dir('part'), folder)
        self.assertEqual(io.extras_dir('part'), folder / 'extras')
        self.assertEqual(io.models_dir(), folder.parent)

    def test_shared_cache_is_ignored(self):
        subprocess.run(['git', 'init', '-q', str(self.home)], check=True)
        io.save_spec('fixture', {'diameter': 3}, 'test fixture')
        cache = self.home / 'models/_shared/specs_cache.json'
        subprocess.run(['git', 'check-ignore', '-q', str(cache)], check=True)

    def test_bad_names(self):
        for name in ['', '.', '..', '../part', 'a/b', 'a\\b']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                io.model_dir(name)

    def test_runtime_and_repo_root_are_protected(self):
        package = self.home / 'package'
        package.mkdir()
        (package / 'package.lock.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'runtime package'):
            io.export_all(Box(2, 2, 2), 'part', out=package / 'models/part')
        os.environ['FORGEAI3D_MODEL_DIR'] = str(package / 'models/part')
        with self.assertRaisesRegex(RuntimeError, 'runtime package'):
            io.model_dir('part')
        del os.environ['FORGEAI3D_MODEL_DIR']
        (self.home / '.git').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'repository root'):
            io.export_all(Box(2, 2, 2), 'part', out=self.home)

    def test_explicit_export_preserves_configured_project(self):
        folder = self.home / 'relocated'
        folder.mkdir()
        ready = folder / 'part.3mf'
        ready.write_bytes(b'configured slicer project sentinel')
        paths = io.export_all(Box(2, 3, 4), 'part', out=folder)
        self.assertEqual(paths['stl'], folder / 'part.stl')
        for kind in ['step', '3mf']:
            self.assertEqual(paths[kind], folder / 'extras' / f'part.{kind}')
        self.assertTrue(all(p.stat().st_size > 0 for p in paths.values()))
        self.assertEqual(ready.read_bytes(), b'configured slicer project sentinel')
        self.assertEqual(io.find_step(paths['stl']), paths['step'])
        self.assertEqual(io.aux_path(paths['stl'], '-preview', '.png'), folder / 'extras/part-preview.png')


if __name__ == '__main__':
    unittest.main()
