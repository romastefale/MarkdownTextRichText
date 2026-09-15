import tempfile
import unittest
from pathlib import Path

from mdtxtrt.conversion.telegram_html import to_html
from mdtxtrt.domain.document import make_node, new_document, normalize_document, plain_text
from mdtxtrt.services.imports import import_file, import_key_for_bytes
from mdtxtrt.storage.sqlite import Store


class IndependentBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "behavior.sqlite3")
        self.uid = 101

    def tearDown(self):
        self.tmp.cleanup()

    def test_user_isolation_revision_navigation_and_duplicate(self):
        doc = new_document()
        doc["nodes"] = [make_node("paragraph", html="first")]
        draft = self.store.create_draft(self.uid, doc)
        with self.assertRaises(KeyError):
            self.store.load_draft(202, draft["id"])
        changed = new_document()
        changed["nodes"] = [make_node("paragraph", html="second")]
        revised = self.store.revise(
            self.uid,
            draft["id"],
            changed,
            draft["session"],
            event_type="behavior",
            parent_revision_id=draft["revision_id"],
        )
        self.assertEqual(self.store.undo(self.uid, draft["id"])["revision_id"], draft["revision_id"])
        self.assertEqual(self.store.redo(self.uid, draft["id"], revised["revision_id"])["revision_id"], revised["revision_id"])
        duplicate = self.store.duplicate_draft(self.uid, draft["id"])
        self.assertNotEqual(duplicate["id"], draft["id"])

    def test_markdown_import_is_idempotent(self):
        raw = b"# Heading\n\nBody"
        key = import_key_for_bytes("behavior", raw)
        first = import_file(self.store, self.uid, name="sample.md", mime="text/markdown", raw=raw, import_key=key)
        second = import_file(self.store, self.uid, name="sample.md", mime="text/markdown", raw=raw, import_key=key)
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["draft"]["id"], second["draft"]["id"])

    def test_plain_text_covers_structured_visible_content(self):
        doc = new_document()
        doc["nodes"] = [
            make_node("paragraph", html="<b>Alpha</b>"),
            make_node("list", ordered=False, items=[{"html": "one"}, {"html": "<i>two</i>"}]),
            make_node("details", summary_html="<b>Summary</b>", html="Body"),
            make_node("table", rows=[[{"html": "<b>Cell</b>"}, {"text": "Plain"}]]),
            make_node("buttons", items=[{"html": "Button", "url": "https://example.com"}]),
        ]
        text = plain_text(doc)
        for visible in ("Alpha", "one", "two", "Summary", "Body", "Cell", "Plain", "Button"):
            with self.subTest(visible=visible):
                self.assertIn(visible, text)

    def test_rich_table_cells_are_sanitized_and_preserved_in_projection(self):
        doc = new_document()
        doc["nodes"] = [make_node(
            "table",
            rows=[[{"html": '<b>Rich</b><script>alert(1)</script><a href="javascript:bad">link</a>'}]],
        )]
        normalized = normalize_document(doc)
        cell = normalized["nodes"][0]["rows"][0][0]["html"]
        self.assertIn("<b>Rich</b>", cell)
        self.assertNotIn("script", cell.lower())
        self.assertNotIn("javascript:", cell.lower())
        projected = to_html(normalized)
        self.assertIn("<td><b>Rich</b>", projected)
        self.assertIn("link", projected)


if __name__ == "__main__":
    unittest.main()
