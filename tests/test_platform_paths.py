"""Platform data locations and explicit overrides preserve portable storage."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arv.legacy_server import data_path


class PlatformPathsTests(unittest.TestCase):
    def location(self, platform, **values):
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"ARV_DB", "ARV_DATA_DIR", "XDG_DATA_HOME", "LOCALAPPDATA"}}
        environment.update(values)
        with patch.dict(os.environ, environment, clear=True), patch.object(sys, "platform", platform), \
             patch.object(Path, "home", return_value=Path("test-user")):
            return data_path()

    def test_windows_uses_local_app_data(self):
        self.assertEqual(self.location("win32", LOCALAPPDATA="local-app-data"),
                         Path("local-app-data/assumption-research-verification/graph.sqlite3"))

    def test_windows_has_a_home_fallback(self):
        self.assertEqual(self.location("win32"),
                         Path("test-user/AppData/Local/assumption-research-verification/graph.sqlite3"))

    def test_existing_macos_location_is_preserved(self):
        self.assertEqual(self.location("darwin"),
                         Path("test-user/Library/Application Support/assumption-research-verification/graph.sqlite3"))

    def test_existing_linux_location_is_preserved(self):
        self.assertEqual(self.location("linux"),
                         Path("test-user/.local/share/assumption-research-verification/graph.sqlite3"))

    def test_explicit_overrides_keep_their_precedence_on_all_platforms(self):
        for platform in ("win32", "darwin", "linux"):
            with self.subTest(platform=platform):
                self.assertEqual(self.location(platform, ARV_DB="chosen.sqlite3", ARV_DATA_DIR="other", XDG_DATA_HOME="xdg"),
                                 Path("chosen.sqlite3"))
                self.assertEqual(self.location(platform, ARV_DATA_DIR="chosen", XDG_DATA_HOME="xdg"),
                                 Path("chosen/graph.sqlite3"))
                self.assertEqual(self.location(platform, XDG_DATA_HOME="xdg"),
                                 Path("xdg/assumption-research-verification/graph.sqlite3"))


if __name__ == "__main__":
    unittest.main()
