"""Host-only checks that export rescue preserves raw evidence and detects changes."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sw/pynq'))
import spectrum_export_rescue as rescue


class RescueChecks(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'build/spectrum_export_rescue_20261030/fixtures' / uuid.uuid4().hex[:12]
        self.base = self.root / 'spectrum_results'
        self.run = self.base / 'spectrum_803d7babfd26'
        self.run.mkdir(parents=True)
        (self.run / 'summary.json').write_text(json.dumps(dict(frames=100, elapsed_s=20,
            reason='DURATION_COMPLETE', stop={'stop_verified': True})), encoding='utf-8')
        (self.run / 'frames.jsonl').write_bytes(b'HOST_TEST_EVIDENCE_ONLY\n')
        (self.base / 'spectrum_invalid_export01.zip').write_bytes(b'HOST_INCOMPLETE_ZIP')
        with zipfile.ZipFile(self.base / 'spectrum_good_export01.zip', 'x') as z:
            z.writestr('HOST_ONLY.txt', 'test')

    def test_inventory_reports_good_and_incomplete_archives(self):
        result = rescue.inventory(self.base)
        self.assertEqual(result['completed_runs'][0]['frames'], 100)
        self.assertEqual(result['archives'][0]['crc'], 'PASS')
        self.assertTrue(result['archives'][1]['crc'].startswith('NOT_COMPLETE_OR_INVALID'))

    def test_backup_matches_raw_bytes_and_hashes_without_changing_sources(self):
        before = {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        result = rescue.backup(self.base, self.root)
        with zipfile.ZipFile(result['file']) as z:
            manifest = json.loads(z.read('rescue_manifest.json'))
            self.assertFalse(manifest['board_accepted'])
            self.assertFalse(any(name.endswith('.zip') for name in z.namelist()))
            for relative, digest in manifest['files_sha256'].items():
                content = z.read(self.base.name + '/' + relative)
                self.assertEqual(content, (self.base / relative).read_bytes())
                self.assertEqual(hashlib.sha256(content).hexdigest().upper(), digest)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_backup_rejects_destination_inside_sources_and_changed_files(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            rescue.backup(self.base, self.base)
        original = rescue.source_files
        calls = []
        def changed(base):
            values = original(base)
            if calls:
                values['HOST_CHANGED_DURING_BACKUP'] = (1, 1)
            calls.append(True)
            return values
        with patch.object(rescue, 'source_files', changed):
            with self.assertRaisesRegex(RuntimeError, 'Source changed'):
                rescue.backup(self.base, self.root)
        self.assertEqual(list(self.root.glob('*.zip')), [])
        self.assertTrue(list(self.root.glob('*.partial')))

    def test_python36_syntax_and_hardware_inert_import(self):
        ast.parse(Path(rescue.__file__).read_text(encoding='utf-8'), feature_version=(3, 6))
        self.assertNotIn('pynq', sys.modules)


if __name__ == '__main__':
    unittest.main(verbosity=2)
