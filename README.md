# SomaFM widget

## Install

Install from the Git repository with:

```bash
omarchy plugin add https://github.com/OWNER/omarchy-somafm.git --enable
```

The repository owner must grant access first because this repository is
private. The widget will appear in the bar; playback starts when you select a
station. To remove it from the bar temporarily, run
`omarchy plugin disable nick.somafm`; enable it again with
`omarchy plugin enable nick.somafm --section right`.

Requirements: Python 3, FFmpeg, and `pw-play` from PipeWire.

## Features

The `nick.somafm` bar widget fetches SomaFM's current channel and playlist
catalog when you click **Validate streams** in the selector. Opening the
selector fetches the catalog automatically only when no verified stations are
loaded; after that, click the button whenever you want to recheck it. The
widget checks each highest-quality playlist and uses the available stream
with the greatest reported bitrate. Select a station to play it; right-click
the bar widget to pause or resume. The popup contains the peak-visualizer
toggle and three color palettes, and opens below the bar widget, sliding left
when needed to stay within the screen edges. Right-click a station to toggle
its favorite status. Favorites appear first; the sort button switches between
alphabetical and most-played order, based on accumulated listening time.
Listening totals accumulate across playback sessions and are saved with the
station cache; **Reset listening times** clears those totals.
The selector is 50% taller than its original layout and accepts typed
station-name prefixes, scrolling the matching station into view. Its validated
station catalog and favorite station records are saved in
`~/.config/omarchy/somafm-stations.json`; opening the selector uses that cache,
and **Validate streams**
refreshes it. Favorite IDs are retained across refreshes, with matching
favorites updated to the newest stream details.
Each station uses its official SomaFM artwork thumbnail in the selector; the
bar displays the station name without artwork.

The widget requires Python 3, FFmpeg, and `pw-play` (PipeWire). FFmpeg decodes
the selected stream to PCM for PipeWire playback and calculates the live
visualizer levels. While a station is playing, the helper requests that
station's current-song JSON every 20 seconds. It does not refresh the catalog
in the background.

Network requests use fixed HTTPS SomaFM endpoints with bounded response sizes
and timeouts. Unverified playlist entries are omitted. Visualizer and palette
preferences are kept in Quickshell persistent properties.
