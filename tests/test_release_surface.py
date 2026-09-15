import os
import unittest
from pathlib import Path
from unittest.mock import patch

from mdtxtrt.config import DEFAULT_MAX_UPLOAD_BYTES, load_settings


ROOT = Path(__file__).resolve().parents[1]


class FinalReleaseSurfaceTests(unittest.TestCase):
    def test_release_bundle_is_the_only_frontend_loaded(self):
        html = (ROOT / 'mdtxtrt/static/index.html').read_text(encoding='utf-8')
        self.assertIn('/static/release.js', html)
        self.assertNotIn('/static/app.js', html)
        self.assertFalse((ROOT / 'mdtxtrt/static/app.js').exists())

    def test_text_controls_expose_final_surface(self):
        html = (ROOT / 'mdtxtrt/static/index.html').read_text(encoding='utf-8')
        js = (ROOT / 'mdtxtrt/static/release.js').read_text(encoding='utf-8')
        for inline in ('strong', 'em', 'u', 'sub', 'sup', 'code'):
            self.assertIn(f'data-inline="{inline}"', html)
        self.assertIn('data-block="code"', html)
        self.assertIn("else if (type === 'code')", js)
        self.assertIn("if (button.dataset.block) return createBlock(button.dataset.block)", js)
        self.assertIn("for (let level = 0; level <= 6; level++)", js)
        self.assertIn("Excluir este trecho?", js)
        self.assertIn("toastUndo('Elemento excluído.'", js)

    def test_upload_limit_has_safe_default_and_validation(self):
        self.assertEqual(DEFAULT_MAX_UPLOAD_BYTES, 20 * 1024 * 1024)
        with patch.dict(os.environ, {'MDTXTRT_MAX_UPLOAD_BYTES': '1048576'}, clear=False):
            self.assertEqual(load_settings().max_upload_bytes, 1048576)
        with patch.dict(os.environ, {'MDTXTRT_MAX_UPLOAD_BYTES': '0'}, clear=False):
            with self.assertRaises(RuntimeError):
                load_settings()
        with patch.dict(os.environ, {'MDTXTRT_MAX_UPLOAD_BYTES': 'invalid'}, clear=False):
            with self.assertRaises(RuntimeError):
                load_settings()


if __name__ == '__main__':
    unittest.main()
