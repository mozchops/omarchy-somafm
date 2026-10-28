# SomaFM widget

![SomaFM bar widget and the station popup with advanced settings open](preview.png)

[SomaFM](https://somafm.com/) offers a free streaming radio service. If you enjoy
listening, please consider [supporting SomaFM](https://somafm.com/support/) to help
keep it running.

## Install

Install from the Git repository with:

```bash
omarchy plugin add https://github.com/mozchops/omarchy-somafm.git --enable
```
The widget will appear in the bar; playback starts when you select a
station. To remove it from the bar temporarily, run
`omarchy plugin disable nick.somafm`; enable it again with
`omarchy plugin enable nick.somafm --section right`.

Requirements: Python 3, FFmpeg, `pw-play` from PipeWire, `python-dbus`,
`python-gobject`, and `wl-clipboard` (for copying song information).

## Uninstall

Remove the widget and its installed plugin files with:

```bash
omarchy plugin remove nick.somafm
```

The station cache, favorites, listening totals, and song history in
`~/.config/omarchy/somafm-stations.json` remain available if you reinstall.

## Features

The bar widget fetches SomaFM's current channel and playlist
catalog when you click **Validate streams** in the selector. Opening the
selector fetches the catalog automatically only when no verified stations are
loaded; after that, click the button whenever you want to recheck it. The
widget checks each highest-quality playlist and uses the available stream
with the greatest reported bitrate, retaining verified alternatives for
fallback. If a connection drops or stalls, playback retries up to six times
with increasing delays, rotating through those alternatives. The popup
distinguishes buffering, playing, paused, reconnecting, stopped, and failed
states; after failure, click **Play** to retry.
Select a station to play it; right-click
the bar widget to pause or resume. Desktop media keys and MPRIS-compatible
controllers can also play, pause, stop, and adjust this widget's volume.
The bar widget is a compact outlined box: a single-column level meter, the
station name, and (when a track is known) ` - ` followed by the track name. The
meter shows the stream's output level, measured before any volume setting is
applied, so system volume and the SomaFM slider don't affect it. The station name
is always shown in full; the track field has a fixed maximum width and shrinks
to fit short titles. When a title is too long it appears from its start, pauses,
scrolls slowly to the end, pauses again, then jumps back and repeats.

The popup keeps the everyday controls on top: the now-playing card, **Pause**,
**Stop**, **Copy song**, an independent SomaFM stream-volume slider (it affects
only this widget's audio, not system volume), the **Stations** and **History**
tabs, search, and the station list. Click **Advanced settings** to reveal
**Validate streams**, the favourites sort, **Reset listening times**,
**Startup playback**, the **Sleep timer**, and the **Show track name** switch.
Turning off **Show track name** hides the track and shrinks the bar widget to
just the meter and station. The popup opens below the bar widget.
Right-click a station to toggle its favorite status. Favorites appear
first; the sort button switches between
alphabetical and most-played order, based on accumulated listening time.
Listening totals accumulate across playback sessions and are saved with the
station cache; the alphabetical/most-played sort choice is saved there too.
**Reset listening times** clears those totals.
The search field filters station names, descriptions, and genres, matching all
typed words. Press Enter to play the first matching station.

The last selected station is remembered without automatically playing it.
Enable **Startup playback** to resume that station when the widget next loads;
this is off by default. The **Sleep timer** button cycles through 15, 30, 60,
and 90 minutes, then off. It stops playback when the time expires, including
if playback is paused or reconnecting; manually stopping also cancels it.

**History** shows the last 30 observed songs, newest first, with their station
and time. Repeated metadata updates for the same song do not create duplicates.
Click a history entry or **Copy song** to copy its title and artist.

Validated station catalog and favorite station records are saved in
`~/.config/omarchy/somafm-stations.json`; opening the selector uses that cache,
and **Validate streams** refreshes it. Favorite IDs are retained across refreshes, 
with matching favorites updated to the newest stream details.
The same file stores song history, the last station, and the startup-playback
and show-track-name choices. The sleep timer is session-only.
Each station uses its official SomaFM artwork thumbnail in the selector; the
bar displays the station name without artwork.

FFmpeg decodes
the selected stream to PCM for PipeWire playback and the helper calculates the
live output level. While a station is playing, the helper requests that
station's current-song JSON every 20 seconds. It does not refresh the catalog
in the background.

Network requests use fixed HTTPS SomaFM endpoints with bounded response sizes
and timeouts. Unverified playlist entries are omitted. The stream-volume
preference is kept in Quickshell persistent properties.

## Development checks

Run the focused streaming, MPRIS, and widget checks with:

```bash
dbus-run-session -- python -m unittest discover -s tests -v
```

The widget integration check uses the installed Omarchy shell in a Wayland
session, with hidden windows, isolated configuration and D-Bus, and simulated
audio and clipboard helpers. It is skipped when that runtime is unavailable.

## License

This plugin is distributed under the [MIT License](LICENSE).
