import json
from pathlib import Path
import selectors
import subprocess
import sys
import time
import unittest

import dbus


class MprisTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "mpris.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self.addCleanup(self.close_process)
        self.assertEqual(self.read_message(), {"type": "ready"})
        self.bus = dbus.SessionBus(private=True)
        self.addCleanup(self.bus.close)
        remote = self.bus.get_object("org.mpris.MediaPlayer2.somafm", "/org/mpris/MediaPlayer2")
        self.player = dbus.Interface(remote, "org.mpris.MediaPlayer2.Player")
        self.properties = dbus.Interface(remote, "org.freedesktop.DBus.Properties")
        self.interface = "org.mpris.MediaPlayer2.Player"

    def close_process(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=3)
        self.process.stdout.close()
        self.process.stderr.close()

    def read_message(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=4), "MPRIS helper did not respond")
        line = self.process.stdout.readline()
        self.assertTrue(line, self.process.stderr.read() if self.process.poll() is not None else "MPRIS helper exited")
        return json.loads(line)

    def update(self, **values):
        self.process.stdin.write(json.dumps(values) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 3
        expected = "Paused" if values.get("state") == "paused" else "Playing"
        while time.monotonic() < deadline:
            properties = self.properties.GetAll(self.interface)
            if properties["PlaybackStatus"] == expected:
                return properties
            time.sleep(0.02)
        self.fail("MPRIS state update was not published")

    def test_controls_and_metadata_are_exposed_without_seeking_or_track_navigation(self):
        properties = self.update(
            station="Groove Salad", title="Example Song", artist="Example Artist",
            state="playing", volume=0.4,
        )
        self.assertEqual(properties["Metadata"]["xesam:title"], "Example Song")
        self.assertEqual(properties["Metadata"]["xesam:artist"], ["Example Artist"])
        self.assertAlmostEqual(properties["Volume"], 0.4)
        for key in ("CanSeek", "CanGoNext", "CanGoPrevious"):
            self.assertFalse(properties[key])
        for method, action in (
            (self.player.PlayPause, "toggle"), (self.player.Pause, "pause"),
            (self.player.Play, "play"), (self.player.Stop, "stop"),
        ):
            method()
            self.assertEqual(self.read_message(), {"type": "command", "action": action})
        properties = self.update(station="Groove Salad", state="paused", volume=0.4)
        self.assertEqual(properties["PlaybackStatus"], "Paused")
        self.properties.Set(self.interface, "Volume", dbus.Double(0.2))
        self.assertEqual(self.read_message(), {"type": "command", "action": "volume", "volume": 0.2})
        with self.assertRaises(dbus.DBusException):
            self.properties.Set(self.interface, "Volume", dbus.Double(1.5))

    def test_invalid_updates_report_an_error_and_exit(self):
        self.process.stdin.write('{"volume":"invalid"}\n')
        self.process.stdin.flush()
        self.assertEqual(self.read_message()["type"], "error")
        self.process.wait(timeout=3)
        self.assertEqual(self.process.returncode, 1)

    def test_utf8_updates_can_arrive_in_separate_reads(self):
        prefix = '{"station":"Caf'.encode() + b"\xc3"
        os_write = self.process.stdin.buffer
        os_write.write(prefix)
        os_write.flush()
        time.sleep(0.1)
        self.assertIsNone(self.process.poll())
        os_write.write(b'\xa9","state":"playing","volume":0.5}\n')
        os_write.flush()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            metadata = self.properties.Get(self.interface, "Metadata")
            if metadata.get("xesam:title") == "Caf\u00e9":
                break
            time.sleep(0.02)
        else:
            self.fail("Split UTF-8 metadata was not published")
