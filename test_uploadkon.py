import tempfile
import unittest
from pathlib import Path

from uploadkon_cli.db import connect_db
from uploadkon_cli.files import cleanup_staged_file, stage_for_upload
from uploadkon_cli.parser import parse_upload_response


SAMPLE_RESPONSE = r"""
[
  {
    "t": "index_info",
    "message_content": "<div class=\"up-box-title\">uploaded</div>\r\n<div class=\"form-group\"><textarea id=\"file1\" readonly=\"readonly\">https:\/\/uploadkon.ir\/uploads\/e37004_26rockstar.mp3<\/textarea><\/div><div class=\"form-group\"><textarea id=\"fileBBC\" readonly=\"readonly\">[url=https:\/\/uploadkon.ir\/uploads\/e37004_26rockstar.mp3]https:\/\/uploadkon.ir\/uploads\/e37004_26rockstar.mp3[\/url]<\/textarea><\/div><div class=\"form-group\"><textarea id=\"delCode\" readonly=\"readonly\">https:\/\/uploadkon.ir\/go.php?go=del&amp;cd=5a28d40674fc6a24b659f750ccf22bc6de6100ef<\/textarea><\/div>"
  }
]
"""


class ParseUploadResponseTests(unittest.TestCase):
    def test_extracts_links_from_uploadkon_response(self) -> None:
        links = parse_upload_response(SAMPLE_RESPONSE)

        self.assertEqual(
            links.direct_url,
            "https://uploadkon.ir/uploads/e37004_26rockstar.mp3",
        )
        self.assertEqual(
            links.delete_url,
            "https://uploadkon.ir/go.php?go=del&cd=5a28d40674fc6a24b659f750ccf22bc6de6100ef",
        )


class DatabaseSchemaTests(unittest.TestCase):
    def test_schema_does_not_include_forum_or_raw_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "links.sqlite3"
            conn = connect_db(db_path)
            columns = [row[1] for row in conn.execute("PRAGMA table_info(uploads)")]
            conn.close()

        self.assertNotIn("forum_url", columns)
        self.assertNotIn("response_json", columns)


class FileStagingTests(unittest.TestCase):
    def test_video_is_zipped_to_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video = temp_path / "clip.mp4"
            video.write_bytes(b"video-bytes")

            staged = stage_for_upload(video, temp_dir=temp_path, zip_videos=True)
            try:
                self.assertTrue(staged.zipped)
                self.assertTrue(staged.is_temp)
                self.assertEqual(staged.upload_name, "clip.mp4.zip")
                self.assertTrue(staged.upload_path.exists())
            finally:
                cleanup_staged_file(staged)

            self.assertFalse(staged.upload_path.exists())


if __name__ == "__main__":
    unittest.main()
