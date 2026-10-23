# SomaFM widget

## Install

Install from the Git repository with:

```bash
omarchy plugin add https://github.com/mozchops/omarchy-somafm.git --enable
```
The widget will appear in the bar; playback starts when you select a
station. To remove it from the bar temporarily, run
`omarchy plugin disable nick.somafm`; enable it again with
`omarchy plugin enable nick.somafm --section right`.

Requirements: Python 3, FFmpeg, and `pw-play` from PipeWire.

## Features

The bar widget fetches SomaFM's current channel and playlist
catalog when you click **Validate streams** in the selector. Opening the
selector fetches the catalog automatically only when no verified stations are
loaded; after that, click the button whenever you want to recheck it. The
widget checks each highest-quality playlist and uses the available stream
with the greatest reported bitrate. Select a station to play it; right-click
the bar widget to pause or resume. The popup contains the peak-visualizer
toggle, you can change the colour palette of the visualiser by clicking on it, 
There is also an independent SomaFM stream-volume slider.
The slider affects only this widget's audio, not system volume. The popup
opens below the bar widget.
Right-click a station to toggle its favorite status. Favorites appear
first; the sort button switches between
alphabetical and most-played order, based on accumulated listening time.
Listening totals accumulate across playback sessions and are saved with the
station cache; the alphabetical/most-played sort choice is saved there too.
**Reset listening times** clears those totals.
Validated station catalog and favorite station records are saved in
`~/.config/omarchy/somafm-stations.json`; opening the selector uses that cache,
and **Validate streams** refreshes it. Favorite IDs are retained across refreshes, 
with matching favorites updated to the newest stream details.
Each station uses its official SomaFM artwork thumbnail in the selector; the
bar displays the station name without artwork.

The widget requires Python 3, FFmpeg, and `pw-play` (PipeWire). FFmpeg decodes
the selected stream to PCM for PipeWire playback and calculates the live
visualizer levels. While a station is playing, the helper requests that
station's current-song JSON every 20 seconds. It does not refresh the catalog
in the background.

Network requests use fixed HTTPS SomaFM endpoints with bounded response sizes
and timeouts. Unverified playlist entries are omitted. Visualizer, palette,
and stream-volume preferences are kept in Quickshell persistent properties.
