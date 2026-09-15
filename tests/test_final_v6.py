import unittest
from pathlib import Path
from mdtxtrt.domain.document import plain_text

ROOT = Path(__file__).resolve().parents[1]

class FinalV6Tests(unittest.TestCase):
    def test_bot_download_is_bounded(self):
        source = (ROOT / "mdtxtrt/telegram/bot.py").read_text(encoding="utf-8")
        self.assertIn("document.file_size", source)
        self.assertIn("class LimitedBuffer(io.BytesIO)", source)
        self.assertIn("self.settings.max_upload_bytes", source)

    def test_selection_is_restored_for_link_and_clear(self):
        source = (ROOT / "mdtxtrt/static/release.js").read_text(encoding="utf-8")
        self.assertIn("function restoreSavedSelection(editableNode)", source)
        self.assertGreaterEqual(source.count("restoreSavedSelection(editableNode)"), 3)

    def test_find_replace_walks_text_nodes(self):
        source = (ROOT / "mdtxtrt/static/release.js").read_text(encoding="utf-8")
        self.assertIn("NodeFilter.SHOW_TEXT", source)
        self.assertIn("replaceVisibleText", source)
        self.assertNotIn("node[key] = node[key].split(find).join(replacement)", source)

    def test_structured_editors_capture_selection(self):
        source = (ROOT / "mdtxtrt/static/release.js").read_text(encoding="utf-8")
        self.assertIn("summary.addEventListener('mouseup', rememberSelection)", source)
        self.assertIn("span.addEventListener('mouseup', rememberSelection)", source)

    def test_html_backed_table_cell_contributes_plain_text(self):
        document = {"nodes": [{"type": "table", "rows": [[{"html": "<strong>Valor</strong>"}]]}]}
        self.assertEqual(plain_text(document), "Valor")

if __name__ == "__main__":
    unittest.main()
