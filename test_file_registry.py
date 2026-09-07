import tempfile
import unittest
from pathlib import Path

from file_registry import FileRegistry


class FileRegistryTests(unittest.TestCase):
    def test_register_link_search_and_missing_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "brief.txt"
            source.write_text("Local AI file", encoding="utf-8")
            database = root / "memory" / "files.sqlite"

            with FileRegistry(database) as registry:
                file_id = registry.register(source, calculate_hash=True)
                registry.link(file_id, "chat-1", message_id="message-2")
                result = registry.search("brief")

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["file_type"], "documents")
                self.assertEqual(result[0]["chat_links"], ["chat-1:message-2"])
                self.assertTrue(result[0]["optional_hash"])
                self.assertEqual(registry.refresh_missing(), 0)

                source.unlink()
                self.assertEqual(registry.refresh_missing(), 1)
                self.assertTrue(registry.search()[0]["is_missing"])

    def test_filters_and_sort_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "cover.png"
            image.write_bytes(b"png")
            with FileRegistry(root / "files.sqlite") as registry:
                registry.register(image, source_type="generated", created_by="agent")
                self.assertEqual(len(registry.search(file_type="images")), 1)
                self.assertEqual(len(registry.search(source_type="uploaded")), 0)
                with self.assertRaises(ValueError):
                    registry.search(sort="random")


if __name__ == "__main__":
    unittest.main()
