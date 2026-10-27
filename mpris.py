#!/usr/bin/env python3
"""Expose the widget's controls through a session-scoped MPRIS service."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys

from somafm import clean_text, emit, valid_thumbnail_url


def main() -> int:
    try:
        import dbus
        import dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
    except ImportError as error:
        emit({"type": "error", "message": f"Media controls require python-dbus and python-gobject: {error}"})
        return 1

    root_interface = "org.mpris.MediaPlayer2"
    player_interface = root_interface + ".Player"
    properties_interface = "org.freedesktop.DBus.Properties"
    DBusGMainLoop(set_as_default=True)

    class MediaPlayer(dbus.service.Object):
        def __init__(self, bus_name: dbus.service.BusName) -> None:
            super().__init__(bus_name, "/org/mpris/MediaPlayer2")
            self.values: dict[str, object] = {}

        def properties(self, interface: str) -> dict[str, object]:
            if interface == root_interface:
                return {
                    "CanQuit": False, "CanRaise": True, "HasTrackList": False,
                    "Identity": "SomaFM",
                    "SupportedUriSchemes": dbus.Array([], signature="s"),
                    "SupportedMimeTypes": dbus.Array([], signature="s"),
                }
            if interface != player_interface:
                raise dbus.exceptions.DBusException(
                    "Unknown interface", name="org.freedesktop.DBus.Error.UnknownInterface",
                )
            station = clean_text(self.values.get("station"), 100)
            title = clean_text(self.values.get("title"), 160)
            artist = clean_text(self.values.get("artist"), 120)
            state = self.values.get("state")
            status = "Paused" if state == "paused" else (
                "Playing" if state in ("playing", "buffering", "reconnecting") else "Stopped"
            )
            metadata = dbus.Dictionary({}, signature="sv")
            if station:
                track_id = hashlib.sha256(f"{station}\n{title}\n{artist}".encode()).hexdigest()
                metadata.update({
                    "mpris:trackid": dbus.ObjectPath("/org/mpris/MediaPlayer2/track/t" + track_id),
                    "xesam:title": title or station,
                    "xesam:artist": dbus.Array([artist] if artist else [], signature="s"),
                    "xesam:album": station,
                })
                image = valid_thumbnail_url(self.values.get("image"))
                if image:
                    metadata["mpris:artUrl"] = image
            return {
                "PlaybackStatus": status, "Metadata": metadata,
                "Volume": dbus.Double(self.values.get("volume", 1.0)),
                "Rate": dbus.Double(1), "MinimumRate": dbus.Double(1), "MaximumRate": dbus.Double(1),
                "Position": dbus.Int64(0),
                "CanGoNext": False, "CanGoPrevious": False, "CanSeek": False,
                "CanPlay": bool(station), "CanPause": status != "Stopped", "CanControl": True,
            }

        @dbus.service.method(properties_interface, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface: str) -> dict[str, object]:
            return self.properties(interface)

        @dbus.service.method(properties_interface, in_signature="ss", out_signature="v")
        def Get(self, interface: str, name: str) -> object:
            properties = self.properties(interface)
            if name not in properties:
                raise dbus.exceptions.DBusException(
                    "Unknown property", name="org.freedesktop.DBus.Error.UnknownProperty",
                )
            return properties[name]

        @dbus.service.method(properties_interface, in_signature="ssv")
        def Set(self, interface: str, name: str, value: object) -> None:
            if interface == player_interface and name == "Volume":
                if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise dbus.exceptions.DBusException(
                        "Volume must be between zero and one", name="org.freedesktop.DBus.Error.InvalidArgs",
                    )
                self.values["volume"] = float(value)
                self.PropertiesChanged(player_interface, {"Volume": dbus.Double(value)}, [])
                emit({"type": "command", "action": "volume", "volume": float(value)})
            elif interface == player_interface and name == "Rate" and value == 1:
                return
            else:
                raise dbus.exceptions.DBusException(
                    "Property is read-only or unsupported", name="org.freedesktop.DBus.Error.PropertyReadOnly",
                )

        @dbus.service.signal(properties_interface, signature="sa{sv}as")
        def PropertiesChanged(self, interface: str, changed: dict[str, object], invalidated: list[str]) -> None:
            pass

        @dbus.service.method(root_interface)
        def Raise(self) -> None:
            emit({"type": "command", "action": "open"})

        @dbus.service.method(root_interface)
        def Quit(self) -> None:
            raise dbus.exceptions.DBusException(
                "Disable the SomaFM widget to quit", name="org.freedesktop.DBus.Error.NotSupported",
            )

        @dbus.service.method(player_interface)
        def PlayPause(self) -> None:
            emit({"type": "command", "action": "toggle"})

        @dbus.service.method(player_interface)
        def Play(self) -> None:
            emit({"type": "command", "action": "play"})

        @dbus.service.method(player_interface)
        def Pause(self) -> None:
            emit({"type": "command", "action": "pause"})

        @dbus.service.method(player_interface)
        def Stop(self) -> None:
            emit({"type": "command", "action": "stop"})

    try:
        bus = dbus.SessionBus()
        name = dbus.service.BusName(root_interface + ".somafm", bus=bus, do_not_queue=True)
        player = MediaPlayer(name)
        loop = GLib.MainLoop()
        pending = b""
        failed = False

        def read_updates(_source: int, _condition: object) -> bool:
            nonlocal pending, failed
            try:
                chunk = os.read(sys.stdin.fileno(), 4096)
                if not chunk:
                    loop.quit()
                    return False
                pending += chunk
                if len(pending) > 65536:
                    raise ValueError("Media update exceeds size limit")
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    values = json.loads(line)
                    if not isinstance(values, dict):
                        raise ValueError("Invalid media update")
                    volume = values.get("volume", 1.0)
                    if not isinstance(volume, (int, float)) or not math.isfinite(volume) or not 0 <= volume <= 1:
                        raise ValueError("Invalid media volume")
                    before = player.properties(player_interface)
                    player.values = values
                    after = player.properties(player_interface)
                    changed = {key: value for key, value in after.items() if value != before[key]}
                    if changed:
                        player.PropertiesChanged(player_interface, changed, [])
                return True
            except (OSError, UnicodeError, ValueError) as error:
                failed = True
                emit({"type": "error", "message": str(error)})
                loop.quit()
                return False

        GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, read_updates)
        emit({"type": "ready"})
        loop.run()
        player.remove_from_connection()
        return 1 if failed else 0
    except dbus.DBusException as error:
        emit({"type": "error", "message": clean_text(str(error), 240)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
