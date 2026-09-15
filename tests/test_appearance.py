import tempfile
import unittest
from pathlib import Path
from mdtxtrt.appearance import ACCENTS, appearance, normalize_accent
from mdtxtrt.storage.sqlite import Store

class AppearanceTests(unittest.TestCase):
    def test_palette_and_default(self):
        self.assertEqual(len(ACCENTS), 7)
        self.assertEqual(appearance({})['accent'], 'laranja')
        self.assertEqual(normalize_accent('  ANIL '), 'anil')
        for value in ('pink', '#fff', None, {}):
            with self.assertRaises(ValueError):
                normalize_accent(value)

    def test_user_isolation_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            store = Store(path)
            store.set_preference(1, 'accent', 'violeta')
            self.assertEqual(appearance(Store(path).preferences(1))['accent'], 'violeta')
            self.assertEqual(appearance(store.preferences(2))['accent'], 'laranja')

if __name__ == '__main__':
    unittest.main()
