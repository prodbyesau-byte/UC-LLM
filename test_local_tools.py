import tempfile
import unittest
import wave
from pathlib import Path

from local_tools import ToolRouter


class LocalToolsTests(unittest.TestCase):
    def test_index_search_operations_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "invoice.txt"
            source.write_text("August invoice total 42", encoding="utf-8")
            duplicate = root / "copy.txt"
            duplicate.write_bytes(source.read_bytes())
            database = root / "state" / "files.sqlite"
            with ToolRouter(database, allowed_roots=[root]) as router:
                result = router.run("FILE_SEARCH", {"roots": [root], "query": "invoice"})
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["result"]["files"][0]["filename"], "invoice.txt")
                copied = router.run("FILE_COPY", {
                    "source": source, "destination": root / "copied.txt"})
                self.assertEqual(copied["status"], "completed")
                indexed_source = router.registry.search_index("invoice")
                self.assertFalse(any(item["path"] == str(source.resolve())
                                     and item["is_missing"] for item in indexed_source))
                self.assertEqual(router.run("FILE_MOVE", {
                    "source": source, "destination": root / "moved.txt"})["status"], "failed")
                moved = router.run("FILE_MOVE", {
                    "source": source, "destination": root / "moved.txt"}, approved=True)
                self.assertEqual(moved["status"], "completed")
                self.assertFalse(source.exists())
                self.assertTrue((root / "moved.txt").exists())
                duplicates = router.run("DUPLICATE_SEARCH", {"directory": root})
                self.assertEqual(duplicates["status"], "completed")
                self.assertTrue(duplicates["result"]["groups"])

    def test_documents_spreadsheet_pdf_and_audio_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "state.sqlite"
            with ToolRouter(database, allowed_roots=[root], generated_root=root / "generated") as router:
                docx = router.run("DOCUMENT_CREATE", {
                    "destination": root / "note.docx", "title": "Note",
                    "content": "A local document"})
                self.assertEqual(docx["status"], "completed")
                self.assertIn("local document", router.run("DOCUMENT_READ", {
                    "path": root / "note.docx"})["result"]["text"])
                pdf = router.run("PDF_CREATE", {
                    "destination": root / "report.pdf", "content": "Page one"})
                self.assertEqual(pdf["status"], "completed")
                self.assertIn("Page one", router.run("PDF_READ", {
                    "path": root / "report.pdf"})["result"]["text"])
                book = router.run("SPREADSHEET_CREATE", {
                    "destination": root / "data.xlsx",
                    "sheets": {"Data": [["Value", "Formula"], [2, "=SUM(A2:A2)"]]},
                    "chart": True})
                self.assertEqual(book["status"], "completed")
                self.assertEqual(router.run("SPREADSHEET_READ", {
                    "path": root / "data.xlsx"})["result"]["sheet_names"], ["Data"])
                wav_path = root / "tone.wav"
                with wave.open(str(wav_path), "wb") as audio:
                    audio.setnchannels(2)
                    audio.setsampwidth(2)
                    audio.setframerate(8000)
                    audio.writeframes((b"\x00\x00" * 8000))
                first = router.run("AUDIO_ANALYZE", {"path": wav_path})
                second = router.run("AUDIO_ANALYZE", {"path": wav_path})
                self.assertEqual(first["status"], "completed")
                self.assertFalse(first["result"]["cache_hit"])
                self.assertTrue(second["result"]["cache_hit"])


if __name__ == "__main__":
    unittest.main()
