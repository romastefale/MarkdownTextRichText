import unittest
from pathlib import Path

from mdtxtrt.conversion.markdown import to_markdown
from mdtxtrt.domain.document import make_node, new_document, normalize_document

ROOT = Path(__file__).resolve().parents[1]


class FinalV10Verification(unittest.TestCase):
    def test_details_body_from_editor_survives_markdown_projection(self):
        doc = new_document()
        doc["nodes"] = [make_node("details", summary_html="<b>Resumo</b>", html="Corpo <i>rico</i>", open=True)]
        projected = to_markdown(normalize_document(doc))
        self.assertIn("<summary>**Resumo**</summary>", projected)
        self.assertIn("Corpo *rico*", projected)

    def test_buttons_items_from_editor_survive_markdown_projection(self):
        doc = new_document()
        doc["nodes"] = [make_node("buttons", items=[{"type": "url", "url": "https://example.com", "html": "<b>Abrir</b>"}])]
        projected = to_markdown(normalize_document(doc))
        self.assertIn("<tg-button-row", projected)
        self.assertIn('url="https://example.com"', projected)
        self.assertIn("**Abrir**", projected)

    def test_html_only_table_cell_survives_markdown_projection_as_visible_text(self):
        doc = new_document()
        doc["nodes"] = [make_node("table", rows=[[{"html": "<b>Rich</b>", "header": True}], [{"html": "Cell"}]])]
        projected = to_markdown(normalize_document(doc))
        self.assertIn("| Rich |", projected)
        self.assertIn("| Cell |", projected)

    def test_editor_patch_keeps_html_as_canonical_table_value(self):
        html = (ROOT / "mdtxtrt/static/index.html").read_text(encoding="utf-8")
        patch = (ROOT / "mdtxtrt/static/final-v10.js").read_text(encoding="utf-8")
        self.assertIn('/static/final-v10.js', html)
        self.assertIn("td.innerHTML = value.html", patch)
        self.assertIn("{html: td.innerHTML}", patch)
        self.assertIn("delete next.text", patch)
        self.assertIn("rememberSelection", patch)


if __name__ == "__main__":
    unittest.main()
