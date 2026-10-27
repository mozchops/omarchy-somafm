#!/usr/bin/env python3
"""SomaFM catalog validation and PipeWire streaming helper."""

from __future__ import annotations

import array
import cmath
import json
import math
import os
import re
import selectors
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


API_HOST = "api.somafm.com"
ICE_HOST = re.compile(r"ice[0-9]+\.somafm\.com\Z")
CHANNEL_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")
SAMPLE_RATE = 44100
FFT_SIZE = 1024
MAX_CHANNELS = 120
MAX_CATALOG_BYTES = 512 * 1024
MAX_PLAYLIST_BYTES = 32 * 1024
OUTPUT_LOCK = threading.Lock()
STOP = False


def emit(payload: dict[str, object]) -> None:
    with OUTPUT_LOCK:
        print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), flush=True)


def clean_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value if ch >= " " and ch != "\x7f").strip()[:limit]


def read_url(url: str, expected_host: str, limit: int, timeout: float = 8) -> tuple[bytes, object]:
    request = Request(url, headers={"User-Agent": "nick.somafm/1.0"})
    with urlopen(request, timeout=timeout) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != expected_host:
            raise ValueError("unexpected redirect host")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("response exceeds size limit")
        return data, response.headers


def valid_playlist_url(value: object, channel_id: str) -> str | None:
    if not isinstance(value, str) or len(value) > 256:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != API_HOST or parsed.port:
        return None
    if not re.fullmatch(rf"/{re.escape(channel_id)}[0-9]*\.pls", parsed.path):
        return None
    return value


def valid_thumbnail_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 300:
        return ""
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != API_HOST
        or parsed.port
        or parsed.fragment
        or not re.fullmatch(r"/logos/120/[A-Za-z0-9-]+120\.(?:png|jpe?g|gif)", parsed.path)
        or (parsed.query and not re.fullmatch(r"v=\d{1,20}", parsed.query))
    ):
        return ""
    return value


def valid_stream_url(value: str, channel_id: str) -> bool:
    if len(value) > 300:
        return False
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or not ICE_HOST.fullmatch(parsed.hostname) or parsed.port:
        return False
    return bool(re.fullmatch(
        rf"/{re.escape(channel_id)}(?:-[a-z0-9]+)+",
        parsed.path,
    ))


def bitrate_from_url(url: str) -> int:
    path = urlparse(url).path.lower()
    match = re.search(r"(?:-|/)(\d{2,3})-(?:mp3|aacp?|ogg|opus)\Z", path)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{2,3})(?:\.(?:mp3|aacp?|ogg|opus))\Z", path)
    return int(match.group(1)) if match else 0


def probe_stream(url: str) -> tuple[bool, int]:
    try:
        request = Request(url, headers={"User-Agent": "nick.somafm/1.0"})
        with urlopen(request, timeout=4) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or not final.hostname or not ICE_HOST.fullmatch(final.hostname):
                return False, 0
            if response.status < 200 or response.status >= 300:
                return False, 0
            value = response.headers.get("icy-br", "")
            match = re.fullmatch(r"\s*(\d{2,3})\s*", value)
            return True, int(match.group(1)) if match else 0
    except (OSError, URLError, ValueError):
        return False, 0


def read_playlist(candidate: tuple[str, str]) -> list[tuple[int, str]]:
    channel_id, playlist_url = candidate
    try:
        data, _ = read_url(playlist_url, API_HOST, MAX_PLAYLIST_BYTES, timeout=6)
        text = data.decode("utf-8", errors="replace")
        streams: list[tuple[int, str]] = []
        for line in text.splitlines():
            if not line.lower().startswith("file") or "=" not in line:
                continue
            stream_url = line.split("=", 1)[1].strip()
            if not valid_stream_url(stream_url, channel_id):
                continue
            bitrate = bitrate_from_url(stream_url)
            streams.append((bitrate, stream_url))
        return streams
    except (OSError, URLError, ValueError):
        return []


def fetch_channel(channel: dict[str, object]) -> dict[str, object] | None:
    channel_id = channel.get("id")
    if not isinstance(channel_id, str) or not CHANNEL_ID.fullmatch(channel_id):
        return None
    playlists = channel.get("playlists")
    if not isinstance(playlists, list) or len(playlists) > 20:
        return None

    candidates: list[tuple[str, str]] = []
    for playlist in playlists:
        if not isinstance(playlist, dict):
            continue
        url = valid_playlist_url(playlist.get("url"), channel_id)
        if url:
            candidates.append((clean_text(playlist.get("quality"), 20).lower(), url))
    highest = [(channel_id, url) for quality, url in candidates if quality == "highest"]
    if not highest:
        highest = [(channel_id, url) for _, url in candidates]
    if not highest:
        return None

    streams: list[tuple[int, str]] = []
    with ThreadPoolExecutor(max_workers=min(2, len(highest))) as pool:
        for result in pool.map(read_playlist, highest):
            streams.extend(result)
    stream_groups: dict[str, list[tuple[int, str]]] = {}
    for bitrate, stream_url in set(streams):
        stream_groups.setdefault(urlparse(stream_url).path, []).append((bitrate, stream_url))

    verified: list[tuple[int, str]] = []
    for candidates_for_path in stream_groups.values():
        for path_bitrate, stream_url in sorted(candidates_for_path, key=lambda item: item[0], reverse=True):
            available, reported_bitrate = probe_stream(stream_url)
            bitrate = reported_bitrate or path_bitrate
            if available and 1 <= bitrate <= 1000:
                verified.append((bitrate, stream_url))

    if not verified:
        return None
    bitrate, stream_url = max(verified, key=lambda item: item[0])
    return {
        "id": channel_id,
        "title": clean_text(channel.get("title"), 100) or channel_id,
        "description": clean_text(channel.get("description"), 280),
        "genre": clean_text(channel.get("genre"), 60),
        "image": valid_thumbnail_url(channel.get("image")),
        "bitrate": bitrate,
        "url": stream_url,
        "streams": [url for _, url in sorted(verified, reverse=True)][:12],
    }


def fetch_catalog() -> dict[str, object]:
    data, _ = read_url(f"https://{API_HOST}/channels.json", API_HOST, MAX_CATALOG_BYTES)
    payload = json.loads(data.decode("utf-8"))
    channels = payload.get("channels") if isinstance(payload, dict) else None
    if not isinstance(channels, list) or not channels or len(channels) > MAX_CHANNELS:
        raise ValueError("invalid channel catalog")

    verified: list[dict[str, object]] = []
    checked = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_channel, channel) for channel in channels if isinstance(channel, dict)]
        for future in as_completed(futures):
            checked += 1
            station = future.result()
            if station:
                verified.append(station)
    verified.sort(key=lambda station: str(station["title"]).casefold())
    return {"stations": verified, "skipped": max(0, checked - len(verified))}


def request_track(channel_id: str) -> dict[str, str]:
    if not CHANNEL_ID.fullmatch(channel_id):
        return {"title": "", "artist": ""}
    try:
        data, _ = read_url(
            f"https://somafm.com/songs/{channel_id}.json",
            "somafm.com",
            64 * 1024,
            timeout=6,
        )
        payload = json.loads(data.decode("utf-8"))
        songs = payload.get("songs") if isinstance(payload, dict) else None
        track = songs[0] if isinstance(songs, list) and songs else {}
        if not isinstance(track, dict):
            track = {}
        return {
            "title": clean_text(track.get("title"), 160),
            "artist": clean_text(track.get("artist"), 120),
        }
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return {"title": "", "artist": ""}


def metadata_worker(channel_id: str, stopped: threading.Event) -> None:
    previous: tuple[str, str] | None = None
    while not stopped.is_set():
        track = request_track(channel_id)
        current = (track["title"], track["artist"])
        if current != previous:
            emit({"type": "track", "title": current[0], "artist": current[1]})
            previous = current
        stopped.wait(20)


def fft(samples: list[float]) -> list[complex]:
    size = len(samples)
    values = [
        complex(samples[index] * (0.5 - 0.5 * math.cos(2 * math.pi * index / (size - 1))), 0)
        for index in range(size)
    ]
    j = 0
    for i in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            values[i], values[j] = values[j], values[i]
    length = 2
    while length <= size:
        root = cmath.exp(-2j * math.pi / length)
        for start in range(0, size, length):
            factor = 1 + 0j
            half = length >> 1
            for offset in range(half):
                even = values[start + offset]
                odd = factor * values[start + offset + half]
                values[start + offset] = even + odd
                values[start + offset + half] = even - odd
                factor *= root
        length <<= 1
    return values


def spectrum(pcm: bytes) -> list[float]:
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    mono = [(samples[index] + samples[index + 1]) / 65536.0 for index in range(0, len(samples), 2)]
    if len(mono) < FFT_SIZE:
        return [0.0] * 12
    values = fft(mono[:FFT_SIZE])
    frequencies = [abs(value) / FFT_SIZE for value in values[:FFT_SIZE // 2]]
    bands: list[float] = []
    for band in range(12):
        low = max(1, int(1.5 * (20000 / 1.5) ** (band / 12)))
        high = max(low + 1, int(1.5 * (20000 / 1.5) ** ((band + 1) / 12)))
        peak = max(frequencies[low:min(high, len(frequencies))] or [0.0])
        decibels = 20 * math.log10(max(peak, 1e-6))
        bands.append(max(0.0, min(1.0, (decibels + 62) / 52)))
    return bands


def apply_volume(pcm: bytes, volume: float) -> bytes:
    if volume >= 1:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    for index, sample in enumerate(samples):
        samples[index] = int(sample * volume)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def stop_children(*children: subprocess.Popen[bytes] | None) -> None:
    for child in children:
        if child and child.poll() is None:
            child.terminate()
    for child in children:
        if child and child.poll() is None:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)


def handle_signal(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def stream_candidates(url: str, channel_id: str, alternatives: object) -> list[str]:
    if not CHANNEL_ID.fullmatch(channel_id) or not valid_stream_url(url, channel_id):
        raise ValueError("Invalid SomaFM stream")
    if not isinstance(alternatives, list) or len(alternatives) > 12:
        raise ValueError("Invalid fallback streams")
    candidates = [url]
    for candidate in alternatives:
        if not isinstance(candidate, str) or not valid_stream_url(candidate, channel_id):
            raise ValueError("Invalid fallback stream")
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def play_stream(url: str, channel_id: str, alternatives: object = None) -> int:
    global STOP
    STOP = False
    try:
        candidates = stream_candidates(url, channel_id, [] if alternatives is None else alternatives)
    except ValueError as error:
        emit({"type": "error", "message": str(error)})
        return 1

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    ffmpeg: subprocess.Popen[bytes] | None = None
    output: subprocess.Popen[bytes] | None = None
    metadata_stop = threading.Event()
    metadata: threading.Thread | None = None
    selector = selectors.DefaultSelector()
    try:
        output = subprocess.Popen(
            ["pw-play", "--raw", "--format", "s16", "--rate", str(SAMPLE_RATE), "--channels", "2", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        if output.stdin is None:
            raise RuntimeError("audio output unavailable")
        metadata = threading.Thread(target=metadata_worker, args=(channel_id, metadata_stop), daemon=True)
        metadata.start()
        emit({"type": "state", "state": "buffering"})
        selector.register(sys.stdin, selectors.EVENT_READ, "command")
        input_buffer = ""
        paused = False
        visualizer_enabled = True
        volume = 1.0
        volume_remainder = b""
        last_audio = time.monotonic()
        last_peak = 0.0
        pending_pcm = bytearray()
        retry_at = 0.0
        failures = 0
        playing_since = 0.0
        announced_playing = False

        def reconnect(reason: str) -> bool:
            nonlocal ffmpeg, failures, retry_at, playing_since, announced_playing, volume_remainder
            if ffmpeg and ffmpeg.stdout:
                try:
                    selector.unregister(ffmpeg.stdout)
                except KeyError:
                    pass
                stop_children(ffmpeg)
                ffmpeg.stdout.close()
            ffmpeg = None
            if playing_since and time.monotonic() - playing_since >= 30:
                failures = 0
            failures += 1
            playing_since = 0.0
            announced_playing = False
            pending_pcm.clear()
            volume_remainder = b""
            if failures > 6:
                emit({"type": "error", "message": reason})
                return False
            retry_at = time.monotonic() + min(2 ** (failures - 1), 8)
            emit({"type": "state", "state": "reconnecting", "attempt": failures})
            emit({"type": "peak", "bands": [0] * 12})
            return True

        while not STOP:
            if output.poll() is not None:
                raise RuntimeError("PipeWire audio output stopped")
            if not paused and ffmpeg is None and time.monotonic() >= retry_at:
                ffmpeg = subprocess.Popen(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-rw_timeout", "15000000",
                        "-i", candidates[failures % len(candidates)],
                        "-vn", "-f", "s16le", "-acodec", "pcm_s16le",
                        "-ac", "2", "-ar", str(SAMPLE_RATE), "pipe:1",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
                if ffmpeg.stdout is None:
                    raise RuntimeError("audio input unavailable")
                selector.register(ffmpeg.stdout, selectors.EVENT_READ, "audio")
                last_audio = time.monotonic()
            for key, _ in selector.select(timeout=0.2):
                if key.data == "command":
                    chunk = os.read(sys.stdin.fileno(), 4096)
                    if not chunk:
                        STOP = True
                        break
                    input_buffer += chunk.decode("utf-8", errors="ignore")
                    while "\n" in input_buffer:
                        line, input_buffer = input_buffer.split("\n", 1)
                        try:
                            command = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        action = command.get("action") if isinstance(command, dict) else ""
                        if action == "pause":
                            if not paused:
                                paused = True
                                if ffmpeg and ffmpeg.stdout:
                                    selector.unregister(ffmpeg.stdout)
                                emit({"type": "state", "state": "paused"})
                        elif action == "resume":
                            if paused:
                                paused = False
                                announced_playing = False
                                playing_since = 0.0
                                last_audio = time.monotonic()
                                if ffmpeg and ffmpeg.stdout:
                                    selector.register(ffmpeg.stdout, selectors.EVENT_READ, "audio")
                                emit({"type": "state", "state": "buffering" if ffmpeg else "reconnecting"})
                        elif action == "stop":
                            STOP = True
                        elif action == "visualizer":
                            visualizer_enabled = command.get("enabled") is True
                            if not visualizer_enabled:
                                emit({"type": "peak", "bands": [0] * 12})
                        elif action == "volume":
                            value = command.get("volume")
                            if isinstance(value, (int, float)) and math.isfinite(value):
                                volume = max(0.0, min(1.0, float(value)))
                elif key.data == "audio" and not paused and not STOP and ffmpeg:
                    chunk = os.read(ffmpeg.stdout.fileno(), 4096)
                    if not chunk:
                        if not reconnect("Audio stream ended after repeated reconnect attempts"):
                            return 1
                        break
                    chunk = volume_remainder + chunk
                    if len(chunk) % 2:
                        volume_remainder = chunk[-1:]
                        chunk = chunk[:-1]
                    else:
                        volume_remainder = b""
                    chunk = apply_volume(chunk, volume)
                    remaining = memoryview(chunk)
                    while remaining:
                        written = output.stdin.write(remaining)
                        if not written:
                            raise RuntimeError("PipeWire audio output closed")
                        remaining = remaining[written:]
                    if chunk and not announced_playing:
                        announced_playing = True
                        playing_since = time.monotonic()
                        emit({"type": "state", "state": "playing"})
                    pending_pcm.extend(chunk)
                    last_audio = time.monotonic()
                    if len(pending_pcm) >= FFT_SIZE * 4:
                        block = bytes(pending_pcm[:FFT_SIZE * 4])
                        del pending_pcm[:FFT_SIZE * 4]
                        if visualizer_enabled and time.monotonic() - last_peak >= 0.08:
                            emit({"type": "peak", "bands": spectrum(block)})
                            last_peak = time.monotonic()
            if not paused and ffmpeg and time.monotonic() - last_audio > 20:
                if not reconnect("Audio stream timed out after repeated reconnect attempts"):
                    return 1
        emit({"type": "state", "state": "stopped"})
        return 0
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        emit({"type": "error", "message": clean_text(str(error), 180) or "Audio playback could not start"})
        return 1
    finally:
        selector.close()
        metadata_stop.set()
        if metadata:
            metadata.join(timeout=1)
        stop_children(ffmpeg, output)
        if ffmpeg and ffmpeg.stdout:
            ffmpeg.stdout.close()
        if output and output.stdin:
            output.stdin.close()


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "catalog":
        try:
            emit(fetch_catalog())
            return 0
        except (OSError, URLError, ValueError, json.JSONDecodeError) as error:
            emit({"error": clean_text(str(error), 180) or "Could not load SomaFM catalog"})
            return 1
    if len(sys.argv) in (4, 5) and sys.argv[1] == "play":
        try:
            alternatives = json.loads(sys.argv[4]) if len(sys.argv) == 5 else []
        except json.JSONDecodeError:
            emit({"type": "error", "message": "Invalid fallback streams"})
            return 1
        return play_stream(sys.argv[2], sys.argv[3], alternatives)
    emit({"error": "Unsupported helper mode"})
    return 2


if __name__ == "__main__":
    sys.exit(main())
