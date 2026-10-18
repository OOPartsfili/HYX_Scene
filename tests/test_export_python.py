"""The downloaded script must contain a valid, runnable scene snapshot."""

import ast
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scene_studio import server
from scene_studio.schema import validate


ROOT = Path(__file__).resolve().parents[1]


class PythonExportTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.scene = json.loads((ROOT / 'scene_studio/templates/Timeline_Demo.json').read_text(encoding='utf-8'))

    def test_export_embeds_unchanged_draft_and_supports_sixty_hz(self):
        draft = copy.deepcopy(self.scene)
        response = self.client.post('/api/export-python', json={'scene': draft, 'hz': 60})
        self.assertEqual(response.status_code, 200, response.get_json(silent=True))
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertIn('60Hz.py', response.headers['Content-Disposition'])
        source = response.get_data(as_text=True)
        self.assertNotIn('__HYX_SCENE_LITERAL__', source)
        tree = ast.parse(source)
        embedded = next(node for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == 'SCENE' for target in node.targets))
        scene = json.loads(embedded.value.args[0].value)
        self.assertEqual(scene, validate({**draft, 'dt': 1/60}))
        self.assertEqual(draft, self.scene)
        self.assertEqual(scene['dt'], 1/60)
        self.assertIn('from scene_studio.engine import Session', source)
        self.assertIn('telemetry.csv', source)
        self.assertNotIn('eye_tracking', source)
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'export.py'
            script.write_text(source, encoding='utf-8')
            result = subprocess.run([sys.executable, str(script), '--help'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--project-root', result.stdout)

    def test_export_rejects_unsupported_frequency_and_bad_scene(self):
        for hz in (0, 30, '60', True):
            with self.subTest(hz=hz):
                response = self.client.post('/api/export-python', json={'scene': self.scene, 'hz': hz})
                self.assertEqual(response.status_code, 400)
        bad = copy.deepcopy(self.scene)
        bad['ego'] = 'missing'
        response = self.client.post('/api/export-python', json={'scene': bad, 'hz': 20})
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
