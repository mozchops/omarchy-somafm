import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SHELL = Path("/usr/share/omarchy/shell")


@unittest.skipUnless(shutil.which("qs") and SHELL.is_dir() and os.environ.get("WAYLAND_DISPLAY"),
                     "Widget integration needs the installed Omarchy shell and a Wayland session")
class WidgetTests(unittest.TestCase):
    def test_widget_interactions_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Commons", "Ui", "services"):
                (root / name).symlink_to(SHELL / name)
            shutil.copyfile(ROOT / "BarWidget.qml", root / "SomaWidget.qml")
            shutil.copyfile(ROOT / "tests/widget.qml", root / "shell.qml")
            home = root / "home"
            plugin = home / ".config/omarchy/plugins/nick.somafm"
            plugin.mkdir(parents=True)
            (plugin / "i18n").symlink_to(ROOT / "i18n")
            (plugin / "mpris.py").write_text(
                f"import runpy, sys\nsys.path.insert(0, {str(ROOT)!r})\n"
                f"runpy.run_path({str(ROOT / 'mpris.py')!r}, run_name='__main__')\n"
            )
            (plugin / "somafm.py").write_text(
                "import json, sys\n"
                "def emit(message): print(json.dumps(message), flush=True)\n"
                "emit({'type':'state','state':'buffering'})\n"
                "for line in sys.stdin:\n"
                " command = json.loads(line)\n"
                " action = command['action']\n"
                " if action == 'volume':\n"
                "  emit({'type':'state','state':'playing'})\n"
                "  emit({'type':'track','title':'Example song','artist':'Example artist'})\n"
                " elif action in ('pause', 'resume'):\n"
                "  emit({'type':'state','state':'paused' if action == 'pause' else 'playing'})\n"
            )
            tools = root / "bin"
            tools.mkdir()
            clipboard = tools / "wl-copy"
            clipboard.write_text(
                f"#!{sys.executable}\nimport pathlib, sys\n"
                f"pathlib.Path({str(root / 'clipboard')!r}).write_text(sys.argv[-1])\n"
            )
            clipboard.chmod(0o755)
            env = dict(
                os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                XDG_STATE_HOME=str(root / "state"), XDG_CACHE_HOME=str(root / "cache"),
                QT_QPA_PLATFORM="wayland", QT_QUICK_BACKEND="software",
                QT_FORCE_STDERR_LOGGING="1", NO_AT_BRIDGE="1", QT_ACCESSIBILITY="0",
                PATH=str(tools) + os.pathsep + os.environ["PATH"],
            )
            result = subprocess.run(
                ["dbus-run-session", "--", "qs", "-p", str(root / "shell.qml"), "--no-color"],
                env=env, capture_output=True, text=True, timeout=15,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("WIDGET_TESTS_PASSED", output, output)
            for error in ("WIDGET_TESTS_FAILED", "ReferenceError", "TypeError", "Binding loop", "ERROR:"):
                self.assertNotIn(error, output, output)
            config = json.loads((home / ".config/omarchy/somafm-stations.json").read_text())
            self.assertEqual(config["lastStation"]["id"], "groovesalad")
            self.assertTrue(config["autoPlay"])
            self.assertEqual(len(config["recentTracks"]), 30)
            self.assertEqual((root / "clipboard").read_text(), "Copied song — Example")
