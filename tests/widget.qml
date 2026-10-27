import QtQuick
import Quickshell

ShellRoot {
  id: test
  property int stage: 0
  property int ticks: 0
  property var sampleStations: [
    { id: "groovesalad", title: "Groove Salad", description: "Chilled beats",
      genre: "Downtempo", bitrate: 128, url: "https://ice1.somafm.com/groovesalad-128-mp3" },
    { id: "dronezone", title: "Drone Zone", description: "Deep space sounds",
      genre: "Ambient", bitrate: 128, url: "https://ice1.somafm.com/dronezone-128-mp3" }
  ]

  function check(condition, message) {
    if (!condition) throw new Error(message)
  }

  function player(message) {
    widget.handlePlayerLine(JSON.stringify(message))
  }

  function media(action) {
    widget.handleMediaLine(JSON.stringify({ type: "command", action: action }))
  }

  QtObject {
    id: fakeBar
    property bool vertical: false
    property int barSize: 32
    property bool barHidden: false
    property string position: "top"
    property color foreground: "#dddddd"
    property color barForeground: foreground
    property color background: "#111111"
    property color urgent: "#ff5555"
    property string fontFamily: "monospace"
  }

  FloatingWindow {
    visible: false
    width: 420
    height: 900
    SomaWidget { id: widget; bar: fakeBar }
  }

  Timer {
    interval: 100
    repeat: true
    running: true
    onTriggered: {
      try {
        test.ticks++
        test.check(test.ticks < 90, "Widget test timed out at stage " + test.stage)
        if (test.stage === 0) {
          if (!widget.stationConfigLoaded || !widget.mediaReady) return
          var config = {
            stations: test.sampleStations, favorites: [test.sampleStations[0]],
            playTimes: {}, lastStation: test.sampleStations[0], autoPlay: false
          }
          widget.loadStationConfig(JSON.stringify(config))
          test.check(widget.currentStation.id === "groovesalad", "Last station not restored")
          test.check(widget.playbackState === "stopped", "Startup playback was not opt-in")
          test.check(!widget.normalizeStation({
            id: "dronezone", title: "Invalid", bitrate: 128, url: test.sampleStations[0].url
          }), "Station accepted another channel's stream")
          widget.searchStations("SPACE ambient")
          test.check(widget.stationRows.length === 2
            && widget.stationRows[1].station.id === "dronezone", "Description/genre filtering failed")
          widget.searchStations("nonexistent")
          test.check(widget.stationRows.length === 0, "Empty filter results failed")
          widget.searchStations("")
          test.check(widget.stationRows[1].station.id === "groovesalad", "Favorites grouping changed")
          test.player({ type: "track", title: "Not heard", artist: "Example" })
          test.check(widget.recentTracks.length === 0, "History recorded a song before playback")
          test.player({ type: "state", state: "playing" })
          test.check(widget.recentTracks.length === 1, "Buffered metadata not recorded on playback")
          test.player({ type: "track", title: "Not heard", artist: "Example" })
          test.check(widget.recentTracks.length === 1, "History duplicated unchanged metadata")
          for (var i = 0; i < 35; i++)
            test.player({ type: "track", title: "Song " + i, artist: "Example" })
          test.check(widget.recentTracks.length === 30 && widget.recentTracks[0].title === "Song 34",
            "History is not bounded/newest first")
          config.autoPlay = true
          config.recentTracks = widget.recentTracks
          widget.loadStationConfig(JSON.stringify(config))
          test.stage = 1
        } else if (test.stage === 1 && widget.playbackState === "playing") {
          test.media("pause")
          test.stage = 2
        } else if (test.stage === 2 && widget.playbackState === "paused") {
          test.check(widget.playbackSegmentStartedAt === 0, "Paused time would count as listening")
          test.media("play")
          test.stage = 3
        } else if (test.stage === 3 && widget.playbackState === "playing") {
          test.player({ type: "state", state: "reconnecting" })
          test.check(widget.playbackSegmentStartedAt === 0 && widget.statusLabel.indexOf("reconnecting") >= 0,
            "Reconnect state/listening accounting failed")
          test.player({ type: "error", message: "Example failure" })
          test.check(widget.playbackState === "failed" && widget.playbackError.indexOf("Example failure") >= 0,
            "Playback failure was not visible")
          test.media("play")
          test.stage = 4
        } else if (test.stage === 4 && widget.playbackState === "playing") {
          for (var minutes of [15, 30, 60, 90, 0]) {
            widget.cycleSleepTimer()
            test.check(widget.sleepMinutes === minutes, "Sleep timer selection failed")
          }
          test.media("pause")
          widget.sleepDeadline = Date.now() + 100
          test.stage = 5
        } else if (test.stage === 5 && widget.sleepDeadline === 0 && widget.playbackState === "stopped") {
          widget.copyTrack({ title: "Copied song", artist: "Example" })
          test.stage = 6
        } else if (test.stage === 6 && widget.copyFeedback !== "") {
          test.check(widget.copyFeedback === "Song copied to clipboard.", "Clipboard feedback failed")
          test.check(widget.recentTracks.length === 30, "History was not preserved on restore")
          widget.saveStationConfig()
          test.stage = 7
        } else if (test.stage === 7) {
          console.log("WIDGET_TESTS_PASSED")
          Qt.quit()
        }
      } catch (error) {
        console.error("WIDGET_TESTS_FAILED", error)
        Qt.quit()
      }
    }
  }
}
