import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import somafm


PRIMARY = "https://ice1.somafm.com/groovesalad-128-mp3"
BACKUP = "https://ice2.somafm.com/groovesalad-128-mp3"


class StreamTests(unittest.TestCase):
    def test_catalog_keeps_verified_backup_servers_in_bitrate_order(self):
        channel = {
            "id": "groovesalad", "title": "Groove Salad",
            "playlists": [{"quality": "highest", "url": "https://api.somafm.com/groovesalad.pls"}],
        }
        lower = "https://ice3.somafm.com/groovesalad-64-aac"
        with patch.object(somafm, "read_playlist", return_value=[(128, PRIMARY), (128, BACKUP), (64, lower)]), \
                patch.object(somafm, "probe_stream", side_effect=lambda url: (True, 64 if url == lower else 128)):
            station = somafm.fetch_channel(channel)
        self.assertEqual(station["bitrate"], 128)
        self.assertEqual(set(station["streams"][:2]), {PRIMARY, BACKUP})
        self.assertEqual(station["streams"][-1], lower)

    def test_fallbacks_are_deduplicated_and_restricted_to_the_same_station(self):
        self.assertEqual(somafm.stream_candidates(PRIMARY, "groovesalad", [PRIMARY, BACKUP]), [PRIMARY, BACKUP])
        for invalid in (
            ["https://example.com/groovesalad-128-mp3"],
            ["https://ice2.somafm.com/dronezone-128-mp3"],
            [None], [BACKUP] * 13, "not a list",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                somafm.stream_candidates(PRIMARY, "groovesalad", invalid)

    def run_player(self, decoder_script, on_message, accelerated=False):
        real_popen = subprocess.Popen
        real_monotonic = time.monotonic
        messages = []
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "attempts"
            audio = Path(directory) / "audio"
            read_fd, write_fd = os.pipe()
            with os.fdopen(read_fd, "r") as commands:
                def spawn(command, **kwargs):
                    if command[0] == "ffmpeg":
                        script = decoder_script
                        args = [str(log), command[command.index("-i") + 1]]
                    else:
                        script = (
                            "import pathlib, sys\n"
                            "with pathlib.Path(sys.argv[1]).open('wb') as output:\n"
                            " while chunk := sys.stdin.buffer.read(4096):\n"
                            "  output.write(chunk); output.flush()\n"
                        )
                        args = [str(audio)]
                    return real_popen([sys.executable, "-u", "-c", script, *args], **kwargs)

                def receive(message):
                    messages.append(message)
                    for action in on_message(message):
                        os.write(write_fd, (json.dumps(action) + "\n").encode())

                try:
                    with patch.object(somafm.subprocess, "Popen", side_effect=spawn), \
                            patch.object(somafm, "emit", side_effect=receive), \
                            patch.object(somafm, "metadata_worker"), \
                            patch.object(somafm.signal, "signal"), \
                            patch.object(somafm.sys, "stdin", commands), \
                            patch.object(somafm.time, "monotonic",
                                         side_effect=lambda: real_monotonic() * (100 if accelerated else 1)):
                        result = somafm.play_stream(PRIMARY, "groovesalad", [BACKUP])
                finally:
                    os.close(write_fd)
            return result, messages, log.read_text().splitlines(), audio.read_bytes() if audio.exists() else b""

    def test_failed_primary_uses_backup_and_accepts_pause_resume_and_volume(self):
        script = (
            "import pathlib, sys, time\n"
            "with pathlib.Path(sys.argv[1]).open('a') as log: log.write(sys.argv[2] + '\\n')\n"
            "if 'ice1.' in sys.argv[2]: sys.exit(1)\n"
            "while True:\n"
            " sys.stdout.buffer.write(b'\\x10\\x00' * 2048); sys.stdout.buffer.flush(); time.sleep(0.02)\n"
        )
        playing = 0

        def commands(message):
            nonlocal playing
            state = message.get("state")
            if state == "buffering":
                return [{"action": "volume", "volume": 0}, {"action": "visualizer", "enabled": False}]
            if state == "playing":
                playing += 1
                return [{"action": "pause" if playing == 1 else "stop"}]
            if state == "paused":
                return [{"action": "resume"}]
            return []

        result, messages, attempts, audio = self.run_player(script, commands)
        self.assertEqual(result, 0)
        self.assertEqual(attempts[:2], [PRIMARY, BACKUP])
        states = [message["state"] for message in messages if message["type"] == "state"]
        self.assertEqual(states, ["buffering", "reconnecting", "playing", "paused", "buffering", "playing", "stopped"])
        self.assertTrue(audio)
        self.assertEqual(set(audio), {0})

    def test_retries_are_bounded_and_failure_is_reported(self):
        script = (
            "import pathlib, sys\n"
            "with pathlib.Path(sys.argv[1]).open('a') as log: log.write(sys.argv[2] + '\\n')\n"
        )
        result, messages, attempts, _ = self.run_player(script, lambda _: [], accelerated=True)
        self.assertEqual(result, 1)
        self.assertEqual(len(attempts), 7)
        self.assertEqual(attempts, [PRIMARY, BACKUP, PRIMARY, BACKUP, PRIMARY, BACKUP, PRIMARY])
        self.assertEqual(messages[-1]["type"], "error")
        self.assertIn("reconnect attempts", messages[-1]["message"])

    def test_stop_during_reconnect_does_not_launch_another_decoder(self):
        script = (
            "import pathlib, sys\n"
            "with pathlib.Path(sys.argv[1]).open('a') as log: log.write(sys.argv[2] + '\\n')\n"
        )
        result, messages, attempts, _ = self.run_player(
            script, lambda message: [{"action": "stop"}] if message.get("state") == "reconnecting" else [],
        )
        self.assertEqual(result, 0)
        self.assertEqual(attempts, [PRIMARY])
        self.assertEqual(messages[-1], {"type": "state", "state": "stopped"})

    def test_invalid_fallback_json_reports_a_protocol_error(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["somafm.py", "play", PRIMARY, "groovesalad", "{"]), \
                contextlib.redirect_stdout(output):
            self.assertEqual(somafm.main(), 1)
        self.assertEqual(json.loads(output.getvalue())["type"], "error")
