"""Host integrity tests for the standalone r3 recorder; no board access."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'sw/pynq/record_spectrum_boot_r3.py'
spec = importlib.util.spec_from_file_location('boot_recorder_r3', SOURCE)
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'build/spectrum_r3_boot_tools_20261031/fixtures' / uuid.uuid4().hex[:12]
        self.root.mkdir(parents=True)
        self.base = self.extract('spectrum_software_v1_r3')
        self.proc = self.root / 'proc'
        (self.proc / 'sys/kernel/random').mkdir(parents=True)
        (self.proc / 'sys/kernel/random/boot_id').write_text('22222222-3333-4444-5555-666666666666')
        (self.proc / 'uptime').write_text('31.25 10.00\n')

    def extract(self, version):
        archive = ROOT / 'release' / version / (version + '_board.zip')
        with zipfile.ZipFile(archive) as z:
            z.extractall(self.root)
        return self.root / version

    def test_accepts_frozen_r3_and_reads_boot_identity(self):
        result = recorder.record(self.base, 'boot01', self.proc)
        self.assertEqual(result['boot_id'], '22222222-3333-4444-5555-666666666666')
        self.assertEqual(result['uptime_s'], 31.25)
        self.assertEqual(result['sha256']['software_manifest.json'], recorder.MANIFEST_SHA256)
        self.assertEqual(result['package_files_verified'], 35)
        self.assertEqual(result['build_revision'], 'spectrum_software_1_r3')
        self.assertTrue(result['actual_power_cycle_requires_operator_confirmation'])

    def test_rejects_r2_package(self):
        with self.assertRaisesRegex(ValueError, 'frozen r3 software manifest'):
            recorder.record(self.extract('spectrum_software_v1_r2'), 'boot01', self.proc)

    def test_rejects_modified_manifest(self):
        path = self.base / 'software_manifest.json'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'frozen r3 software manifest'):
            recorder.record(self.base, 'boot01', self.proc)

    def test_rejects_changed_application_and_bitstream(self):
        for name in ('spectrum_app.py', 'fft.bit'):
            with self.subTest(name=name):
                path = self.base / name
                original = path.read_bytes()
                path.write_bytes(original + b'x')
                with self.assertRaisesRegex(ValueError, 'Package source differs'):
                    recorder.record(self.base, 'boot01', self.proc)
                path.write_bytes(original)

    def test_rejects_changed_notebook_source_and_extra_code(self):
        path = self.base / 'Spectrum_analyzer.ipynb'
        original = path.read_bytes()
        notebook = json.loads(original)
        notebook['cells'][0]['source'] = ['modified source']
        path.write_text(json.dumps(notebook), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Notebook source differs'):
            recorder.record(self.base, 'boot01', self.proc)
        notebook = json.loads(original)
        notebook['cells'].append(dict(cell_type='code', source=['print(1)'], outputs=[]))
        path.write_text(json.dumps(notebook), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'nonempty extra Notebook cell'):
            recorder.record(self.base, 'boot01', self.proc)

    def test_accepts_saved_notebook_outputs(self):
        path = self.base / 'Spectrum_analyzer.ipynb'
        notebook = json.loads(path.read_bytes())
        cell = next(c for c in notebook['cells'] if c['cell_type'] == 'code')
        cell['execution_count'] = 1
        cell['outputs'] = [dict(output_type='stream', name='stdout', text=['HOST FIXTURE\n'])]
        path.write_text(json.dumps(notebook), encoding='utf-8')
        self.assertEqual(recorder.record(self.base, 'boot02', self.proc)['build_revision'], 'spectrum_software_1_r3')

    def test_compatible_syntax_and_no_hardware_imports(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'), feature_version=(3, 6))
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        imports.update(a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names)
        self.assertFalse({'pynq', 'spectrum_app', 'spectrum_runtime'} & imports)


if __name__ == '__main__':
    unittest.main()
