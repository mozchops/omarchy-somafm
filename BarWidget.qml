import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "nick.somafm"

  property bool popupOpen: false
  property bool loadingStations: false
  property string catalogError: ""
  property string catalogWarning: ""
  property var stations: []
  property var currentStation: null
  property string trackTitle: ""
  property string trackArtist: ""
  property string playbackState: "stopped"
  property double playbackSegmentStartedAt: 0
  property int listeningClockTick: 0
  property var stationRows: []
  property string stationSearch: ""
  property bool stationConfigLoaded: false
  property var savedFavoriteStations: []
  property var translationStrings: ({})
  property var peakBands: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
  property var palettes: ({
    "Spectrum": ["#ff5f6d", "#ff8a5b", "#ffc857", "#e6f14a", "#8de969", "#48d597", "#28c5c9", "#42a5f5", "#7d83ff", "#ae72ef", "#e06bd7", "#ff6f91"],
    "Aurora": ["#62e6c8", "#56d8d3", "#52c2e8", "#5eacf2", "#788ef2", "#9b7cf1", "#bd79e7", "#d777d0", "#e47fba", "#e894a8", "#efb69e", "#f2d49a"],
    "Monochrome": ["#f2f2f2", "#e5e5e5", "#d8d8d8", "#cbcbcb", "#bebebe", "#b1b1b1", "#a4a4a4", "#979797", "#8a8a8a", "#7d7d7d", "#707070", "#636363"]
  })
  readonly property var paletteNames: ["Spectrum", "Aurora", "Monochrome"]
  readonly property bool opened: popupOpen
  readonly property string label: currentStation
    ? currentStation.title
    : strings.t("widget.noStation")
  readonly property string trackLabel: trackTitle
    ? trackTitle + (trackArtist ? " — " + trackArtist : "")
    : ""
  readonly property bool isPlaying: playbackState === "playing"
  readonly property bool visualizerActive: persisted.visualizerEnabled && isPlaying
  readonly property string helperPath: Quickshell.env("HOME")
    + "/.config/omarchy/plugins/nick.somafm/somafm.py"
  readonly property string stationConfigPath: Quickshell.env("HOME")
    + "/.config/omarchy/somafm-stations.json"

  QtObject {
    id: strings

    function t(key) {
      var value = root.translationStrings[key]
      return typeof value === "string" ? value : key
    }
  }

  FileView {
    id: translationFile
    path: Quickshell.env("HOME") + "/.config/omarchy/plugins/nick.somafm/i18n/en.json"
    onLoaded: {
      try {
        var loaded = JSON.parse(text())
        if (!loaded || typeof loaded !== "object" || Array.isArray(loaded))
          throw new Error("invalid translation file")
        root.translationStrings = loaded
      } catch (error) {
        console.warn("nick.somafm: could not load translations: " + error)
      }
    }
    onLoadFailed: function(error) {
      console.warn("nick.somafm: could not load translations: " + error)
    }
  }

  FileView {
    id: stationConfigFile
    path: root.stationConfigPath
    onLoaded: root.loadStationConfig(text())
    onLoadFailed: root.loadStationConfig("")
    onSaveFailed: root.catalogError = strings.t("popup.configError")
  }

  Component.onCompleted: stationConfigFile.reload()

  function isFavorite(stationId) {
    return persisted.favoriteIds.indexOf(stationId) >= 0
  }

  function toggleFavorite(station) {
    var favorites = persisted.favoriteIds.slice()
    var index = favorites.indexOf(station.id)
    if (index >= 0) favorites.splice(index, 1)
    else favorites.push(station.id)
    persisted.favoriteIds = favorites
    refreshSavedFavorites()
    rebuildStationRows()
    saveStationConfig()
  }

  function toggleFavoriteSort() {
    persisted.favoriteSort = persisted.favoriteSort === "time" ? "name" : "time"
    rebuildStationRows()
    saveStationConfig()
  }

  function setPlaybackVolume(position, width) {
    if (width <= 0) return
    var volume = Math.max(0, Math.min(1, Math.round(position / width * 100) / 100))
    if (persisted.playbackVolume !== volume)
      persisted.playbackVolume = volume
  }

  function resetListeningTimes() {
    recordPlayTime()
    persisted.playTimes = ({})
    rebuildStationRows()
    saveStationConfig()
  }

  function recordPlayTime() {
    if (!currentStation || playbackSegmentStartedAt <= 0) return
    var elapsed = Math.floor((Date.now() - playbackSegmentStartedAt) / 1000)
    if (elapsed <= 0) return
    var totals = Object.assign({}, persisted.playTimes || {})
    totals[currentStation.id] = Math.max(0, Number(totals[currentStation.id]) || 0) + elapsed
    persisted.playTimes = totals
    playbackSegmentStartedAt += elapsed * 1000
    saveStationConfig()
  }

  function formatListeningTime(stationId) {
    var tick = listeningClockTick
    var totalSeconds = Number(persisted.playTimes[stationId]) || 0
    if (isPlaying && currentStation && currentStation.id === stationId
        && playbackSegmentStartedAt > 0)
      totalSeconds += Math.floor((Date.now() - playbackSegmentStartedAt) / 1000)
    var totalMinutes = Math.floor(totalSeconds / 60)
    var days = Math.floor(totalMinutes / 1440)
    var hours = Math.floor((totalMinutes % 1440) / 60)
    var minutes = totalMinutes % 60
    var pad = function(value) { return value < 10 ? "0" + value : String(value) }
    return pad(days) + ":" + pad(hours) + ":" + pad(minutes)
  }

  function rebuildStationRows() {
    var favorites = []
    var others = []
    for (var i = 0; i < stations.length; i++) {
      if (isFavorite(stations[i].id)) favorites.push(stations[i])
      else others.push(stations[i])
    }
    var sortByName = function(a, b) {
      return a.title.toLowerCase().localeCompare(b.title.toLowerCase())
    }
    if (persisted.favoriteSort === "time") {
      favorites.sort(function(a, b) {
        var difference = (Number(persisted.playTimes[b.id]) || 0)
          - (Number(persisted.playTimes[a.id]) || 0)
        return difference || sortByName(a, b)
      })
    } else {
      favorites.sort(sortByName)
    }
    others.sort(sortByName)

    var rows = []
    if (favorites.length > 0) {
      rows.push({ type: "header", title: strings.t("popup.favourites") })
      favorites.forEach(function(station) {
        rows.push({ type: "station", station: station })
      })
    }
    if (others.length > 0) {
      rows.push({ type: "header", title: strings.t("popup.allStations") })
      others.forEach(function(station) {
        rows.push({ type: "station", station: station })
      })
    }
    stationRows = rows
  }

  function normalizeStation(station) {
    if (!station || typeof station !== "object"
        || !/^[a-z0-9][a-z0-9-]{0,47}$/.test(station.id || "")
        || typeof station.title !== "string" || typeof station.url !== "string"
        || !/^https:\/\/ice[0-9]+\.somafm\.com\/[a-z0-9-]+$/.test(station.url)
        || !Number.isInteger(Number(station.bitrate)) || Number(station.bitrate) < 1) return null
    var image = typeof station.image === "string"
        && /^https:\/\/api\.somafm\.com\/logos\/120\/[A-Za-z0-9-]+120\.(?:png|jpe?g|gif)(?:\?v=\d{1,20})?$/.test(station.image)
      ? station.image : ""
    return {
      id: station.id,
      title: station.title.slice(0, 100),
      description: String(station.description || "").slice(0, 280),
      genre: String(station.genre || "").slice(0, 60),
      image: image,
      bitrate: Number(station.bitrate),
      url: station.url
    }
  }

  function stationForId(list, id) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === id) return list[i]
    }
    return null
  }

  function refreshSavedFavorites() {
    var updated = []
    for (var i = 0; i < persisted.favoriteIds.length; i++) {
      var id = persisted.favoriteIds[i]
      var station = stationForId(stations, id) || stationForId(savedFavoriteStations, id)
      if (station) updated.push(station)
    }
    savedFavoriteStations = updated
  }

  function loadStationConfig(raw) {
    stationConfigLoaded = true
    if (!String(raw || "").trim()) {
      rebuildStationRows()
      return
    }
    try {
      if (raw.length > 1024 * 1024) throw new Error("station config is too large")
      var config = JSON.parse(raw)
      if (!config || !Array.isArray(config.stations) || !Array.isArray(config.favorites)
          || config.favorites.length > 1000)
        throw new Error("invalid station config")

      var loadedStations = []
      for (var i = 0; i < Math.min(config.stations.length, 120); i++) {
        var station = normalizeStation(config.stations[i])
        if (station) loadedStations.push(station)
      }
      stations = loadedStations

      var loadedFavorites = []
      var favoriteIds = []
      for (var j = 0; j < config.favorites.length; j++) {
        var favorite = normalizeStation(config.favorites[j])
        if (favorite && favoriteIds.indexOf(favorite.id) < 0) {
          loadedFavorites.push(favorite)
          favoriteIds.push(favorite.id)
        }
      }
      savedFavoriteStations = loadedFavorites
      persisted.favoriteIds = favoriteIds
      var loadedPlayTimes = Object.assign({}, persisted.playTimes || {})
      if (config.playTimes && typeof config.playTimes === "object" && !Array.isArray(config.playTimes)) {
        for (var id in config.playTimes) {
          if (!/^[a-z0-9][a-z0-9-]{0,47}$/.test(id)) continue
          var seconds = Number(config.playTimes[id])
          if (Number.isFinite(seconds) && seconds >= 0)
            loadedPlayTimes[id] = Math.max(Number(loadedPlayTimes[id]) || 0, seconds)
        }
      }
      persisted.playTimes = loadedPlayTimes
      if (config.favoriteSort === "name" || config.favoriteSort === "time")
        persisted.favoriteSort = config.favoriteSort
      refreshSavedFavorites()
      rebuildStationRows()
      saveStationConfig()
    } catch (error) {
      catalogError = strings.t("popup.configError")
    }
  }

  function saveStationConfig() {
    if (!stationConfigLoaded) return
    stationConfigFile.setText(JSON.stringify({
      version: 1,
      stations: stations,
      favorites: savedFavoriteStations,
      favoriteSort: persisted.favoriteSort,
      playTimes: persisted.playTimes || ({})
    }, null, 2) + "\n")
  }

  function searchStations(query) {
    stationSearch = query.toLowerCase()
    if (!stationSearch) return
    for (var i = 0; i < stationRows.length; i++) {
      var row = stationRows[i]
      if (row.type === "station" && row.station.title.toLowerCase().indexOf(stationSearch) === 0) {
        stationList.currentIndex = i
        stationList.positionViewAtIndex(i, ListView.Beginning)
        return
      }
    }
  }

  function handleSearchKey(event) {
    if (event.key === Qt.Key_Escape) {
      popup.close()
      event.accepted = true
      return
    }
    if (event.key === Qt.Key_Backspace) {
      searchStations(stationSearch.slice(0, -1))
      event.accepted = true
      return
    }
    if (event.text && /^[a-z0-9 -]$/i.test(event.text)) {
      searchStations(stationSearch + event.text)
      event.accepted = true
    }
  }

  PersistentProperties {
    id: persisted
    reloadableId: "nick.somafm"
    property bool visualizerEnabled: true
    property string paletteName: "Spectrum"
    property var favoriteIds: []
    property var playTimes: ({})
    property string favoriteSort: "name"
    property real playbackVolume: 1.0

    onFavoriteIdsChanged: root.rebuildStationRows()
    onPlayTimesChanged: root.rebuildStationRows()
    onPlaybackVolumeChanged: root.sendPlayerCommand("volume", playbackVolume)
  }

  implicitWidth: contentRow.implicitWidth + Style.space(14)
  implicitHeight: barSize

  onPopupOpenChanged: if (popupOpen) stationSearch = ""
  onStationConfigLoadedChanged: {
    if (stationConfigLoaded && popupOpen && stations.length === 0 && !loadingStations)
      validateStreams()
  }

  function openSelector() {
    popupOpen = true
    if (stationConfigLoaded && stations.length === 0 && !loadingStations)
      validateStreams()
  }

  function validateStreams() {
    if (catalogProcess.running) return
    catalogError = ""
    catalogWarning = ""
    loadingStations = true
    catalogProcess.running = true
  }

  function toggleSelector() {
    if (popupOpen) popupOpen = false
    else openSelector()
  }

  function open() {
    openSelector()
  }

  function close() {
    popupOpen = false
  }

  function startStation(station) {
    if (!station || !station.url || !station.id) return
    recordPlayTime()
    pendingStation = station
    if (playerProcess.running) playerProcess.running = false
    else launchPendingStation()
  }

  property var pendingStation: null

  function launchPendingStation() {
    if (!pendingStation) return
    currentStation = pendingStation
    pendingStation = null
    trackTitle = ""
    trackArtist = ""
    playbackState = "starting"
    playbackSegmentStartedAt = 0
    playerProcess.command = [
      "python3", helperPath, "play", currentStation.url, currentStation.id
    ]
    playerProcess.running = true
  }

  function stopPlayback() {
    recordPlayTime()
    pendingStation = null
    if (playerProcess.running) playerProcess.running = false
    playbackState = "stopped"
    trackTitle = ""
    trackArtist = ""
  }

  function togglePlayback() {
    if (!currentStation) return
    if (playbackState === "playing") sendPlayerCommand("pause")
    else if (playbackState === "paused") sendPlayerCommand("resume")
    else if (playbackState === "stopped") startStation(currentStation)
  }

  function sendPlayerCommand(action, extra) {
    if (!playerProcess.running) return
    var message = { action: action }
    if (action === "visualizer") message.enabled = extra
    else if (action === "volume") message.volume = extra
    playerProcess.write(JSON.stringify(message) + "\n")
  }

  function finishCatalog(raw) {
    loadingStations = false
    try {
      var result = JSON.parse(String(raw || "").trim())
      if (!result || !(result.stations instanceof Array)) throw new Error("invalid catalog")
      var verified = []
      for (var i = 0; i < Math.min(result.stations.length, 120); i++) {
        var station = normalizeStation(result.stations[i])
        if (station) verified.push(station)
      }
      if (verified.length > 0) {
        stations = verified
        if (currentStation) {
          var refreshedCurrent = stationForId(verified, currentStation.id)
          if (refreshedCurrent) currentStation = refreshedCurrent
        }
        refreshSavedFavorites()
        saveStationConfig()
      }
      rebuildStationRows()
      if (Number(result.skipped) > 0) catalogWarning = strings.t("popup.partial")
      if (verified.length === 0) catalogError = strings.t("popup.empty")
    } catch (error) {
      catalogError = strings.t("popup.fetchError")
    }
  }

  function handlePlayerLine(line) {
    try {
      var message = JSON.parse(String(line || "").trim())
      if (message.type === "state") {
        if (message.state === "playing" && playbackState !== "playing")
          playbackSegmentStartedAt = Date.now()
        else if (message.state !== "playing" && playbackState === "playing")
          recordPlayTime()
        playbackState = message.state
      }
      else if (message.type === "track") {
        trackTitle = String(message.title || "").slice(0, 160)
        trackArtist = String(message.artist || "").slice(0, 120)
      } else if (message.type === "peak" && message.bands instanceof Array) {
        peakBands = message.bands.slice(0, 12).map(function(value) {
          return Math.max(0, Math.min(1, Number(value) || 0))
        })
      } else if (message.type === "error") {
        recordPlayTime()
        playbackState = "stopped"
        catalogError = strings.t("popup.audioError")
      }
    } catch (error) {
      playbackState = "stopped"
    }
  }

  function paletteColor(index) {
    var palette = palettes[persisted.paletteName] || palettes.Spectrum
    return palette[index % palette.length]
  }

  function cyclePalette() {
    var index = paletteNames.indexOf(persisted.paletteName)
    persisted.paletteName = paletteNames[(index + 1) % paletteNames.length]
  }

  Row {
    id: contentRow
    anchors.centerIn: parent
    spacing: Style.space(6)
    property real stationWidth: Math.min(stationText.implicitWidth, Style.space(100))
    property real trackAvailableWidth: Math.max(
      0, Style.space(360) - stationWidth
        - (visualizer.visible ? visualizer.implicitWidth : 0) - Style.space(18)
    )
    property real trackWidth: Math.min(trackText.implicitWidth, trackAvailableWidth)

    Text {
      textFormat: Text.PlainText
      text: root.isPlaying ? "󰝚" : "󰓃"
      color: root.bar ? root.bar.barForeground : "white"
      font.family: root.bar ? root.bar.fontFamily : "monospace"
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
    }

    Item {
      width: contentRow.stationWidth
        + (root.trackLabel ? Style.space(6) + contentRow.trackWidth : 0)
      height: root.barSize
      clip: true
      anchors.verticalCenter: parent.verticalCenter
      visible: !root.bar.vertical

      Row {
        id: titleRow
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(6)

        Text {
          id: stationText
          textFormat: Text.PlainText
          text: root.label
          color: root.bar ? root.bar.barForeground : "white"
          font.family: root.bar ? root.bar.fontFamily : "monospace"
          font.pixelSize: Style.font.bodySmall
          anchors.verticalCenter: parent.verticalCenter
          elide: Text.ElideRight
          width: contentRow.stationWidth
        }

        Item {
          id: trackClip
          width: root.trackLabel ? contentRow.trackWidth : 0
          height: root.barSize
          clip: true
          anchors.verticalCenter: parent.verticalCenter
          visible: root.trackLabel !== ""

          Text {
            id: trackText
            textFormat: Text.PlainText
            text: root.trackLabel
            color: root.bar ? root.bar.barForeground : "white"
            font.family: root.bar ? root.bar.fontFamily : "monospace"
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.NoWrap
            elide: Text.ElideNone
            anchors.verticalCenter: parent.verticalCenter

            NumberAnimation on x {
              id: trackScroll
              running: trackText.implicitWidth > trackClip.width && root.isPlaying
                && root.visible && !root.bar.barHidden && !root.popupOpen && !root.bar.vertical
              onRunningChanged: if (!running) trackText.x = 0
              loops: Animation.Infinite
              from: trackClip.width
              to: -trackText.implicitWidth
              duration: Math.max(10000, (trackText.implicitWidth + trackClip.width) * 45)
              easing.type: Easing.Linear
            }
          }
        }
      }
    }

    Item {
      id: visualizer
      visible: root.visualizerActive || root.popupOpen
      implicitWidth: peakColumns.implicitWidth
      width: visible ? implicitWidth : 0
      height: root.barSize
      anchors.verticalCenter: parent.verticalCenter

      Row {
        id: peakColumns
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)
        opacity: root.visualizerActive

        Repeater {
          model: 12

          Rectangle {
            required property int index
            width: Style.space(3)
            height: Math.max(Style.space(2), root.barSize * (root.peakBands[index] || 0) * 0.55)
            anchors.verticalCenter: parent.verticalCenter
            radius: Style.space(2)
            color: root.paletteColor(index)
          }
        }
      }

    }
  }

  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    cursorShape: Qt.PointingHandCursor
    onClicked: function(mouse) {
      if (mouse.button === Qt.RightButton) root.togglePlayback()
      else {
        var visualizerOrigin = visualizer.mapToItem(root, 0, 0)
        if (root.visualizerActive
            && mouse.x >= visualizerOrigin.x && mouse.x <= visualizerOrigin.x + visualizer.width
            && mouse.y >= visualizerOrigin.y && mouse.y <= visualizerOrigin.y + visualizer.height)
          root.cyclePalette()
        else
          root.toggleSelector()
      }
    }
  }

  Process {
    id: catalogProcess
    command: ["python3", root.helperPath, "catalog"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.finishCatalog(text)
    }
    stderr: StdioCollector { waitForEnd: true }
  }

  Process {
    id: playerProcess
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { root.handlePlayerLine(line) }
    }
    stderr: StdioCollector { waitForEnd: true }
    onStarted: {
      root.sendPlayerCommand("volume", persisted.playbackVolume)
      root.sendPlayerCommand("visualizer", persisted.visualizerEnabled)
    }
    onExited: {
      if (root.pendingStation) root.launchPendingStation()
      else if (root.playbackState !== "stopped") {
        root.recordPlayTime()
        root.playbackState = "stopped"
      }
    }
  }

  Timer {
    interval: 5000
    repeat: true
    running: root.isPlaying
    onTriggered: root.recordPlayTime()
  }

  Timer {
    interval: 1000
    repeat: true
    running: root.isPlaying
    onTriggered: root.listeningClockTick++
  }

  Timer {
    id: searchResetTimer
    interval: 1000
    onTriggered: root.stationSearch = ""
  }

  KeyboardPanel {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.popupOpen
    focusTarget: searchKeys
    centerOnBar: false
    contentWidth: popup.fittedContentWidth(Style.space(380))
    contentHeight: popup.fittedContentHeight(panelContent.implicitHeight)

    Column {
      id: panelContent
      anchors.fill: parent
      spacing: Style.space(10)

      Column {
        width: parent.width
        spacing: Style.space(2)

        Text {
          textFormat: Text.PlainText
          text: strings.t("popup.title")
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.subtitle
          font.bold: true
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: strings.t("popup.validateSubtitle")
          color: Qt.darker(root.bar.foreground, 1.35)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }

      Row {
        width: parent.width
        spacing: Style.space(8)

        Button {
          width: (parent.width - Style.space(8)) / 2
          text: strings.t("popup.validateStreams")
          foreground: root.bar.foreground
          bordered: true
          enabled: !root.loadingStations
          opacity: enabled ? 1.0 : 0.55
          onClicked: root.validateStreams()
        }

        Button {
          width: (parent.width - Style.space(8)) / 2
          text: strings.t("popup.sortFavourites").arg(
            strings.t(persisted.favoriteSort === "time" ? "popup.sortTime" : "popup.sortName")
          )
          foreground: root.bar.foreground
          bordered: true
          onClicked: root.toggleFavoriteSort()
        }
      }

      Button {
        width: parent.width
        text: strings.t("popup.resetListeningTimes")
        foreground: root.bar.foreground
        bordered: true
        onClicked: root.resetListeningTimes()
      }

      Rectangle {
        width: parent.width
        height: Style.space(52)
        radius: Style.spacing.labelGap
        color: Qt.alpha(root.bar.foreground, 0.06)

        Column {
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(10)
          spacing: Style.space(3)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.currentStation ? root.currentStation.title : strings.t("widget.noStation")
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.trackTitle
              ? root.trackTitle + (root.trackArtist ? " — " + root.trackArtist : "")
              : (root.playbackState === "starting" ? strings.t("popup.starting")
                : (root.playbackState === "playing" ? strings.t("popup.unknownTrack")
                  : (root.playbackState === "paused" ? strings.t("popup.paused")
                    : (root.currentStation ? strings.t("popup.stopped") : strings.t("popup.idle")))))
            color: Qt.darker(root.bar.foreground, 1.35)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }
      }

      Column {
        width: parent.width
        spacing: Style.space(4)

        Row {
          width: parent.width

          Text {
            textFormat: Text.PlainText
            text: strings.t("popup.streamVolume")
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            width: parent.width - volumeValue.implicitWidth
          }

          Text {
            id: volumeValue
            textFormat: Text.PlainText
            text: Math.round(persisted.playbackVolume * 100) + "%"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            horizontalAlignment: Text.AlignRight
          }
        }

        Rectangle {
          id: volumeTrack
          width: parent.width
          height: Style.space(20)
          color: "transparent"

          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: Style.space(6)
            radius: height / 2
            color: Qt.alpha(root.bar.foreground, 0.18)
          }

          Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width * persisted.playbackVolume
            height: Style.space(6)
            radius: height / 2
            color: Commons.Color.accent
          }

          Rectangle {
            x: Math.max(0, Math.min(parent.width - width,
              parent.width * persisted.playbackVolume - width / 2))
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(14)
            height: width
            radius: width / 2
            color: root.bar.foreground
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onPressed: function(mouse) { root.setPlaybackVolume(mouse.x, width) }
            onPositionChanged: function(mouse) {
              if (pressed) root.setPlaybackVolume(mouse.x, width)
            }
          }
        }
      }

      Row {
        id: visualizerSettings
        width: parent.width
        spacing: Style.space(8)

        Text {
          id: visualizerLabel
          textFormat: Text.PlainText
          text: strings.t("popup.visualizer")
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width - visualizerToggle.width - Style.space(8)
        }

        Rectangle {
          id: visualizerToggle
          width: Style.space(42)
          height: Style.space(24)
          radius: Style.space(12)
          color: persisted.visualizerEnabled ? Commons.Color.accent : Qt.alpha(root.bar.foreground, 0.15)
          anchors.verticalCenter: parent.verticalCenter

          Rectangle {
            width: Style.space(18)
            height: Style.space(18)
            radius: width / 2
            y: Style.space(3)
            x: persisted.visualizerEnabled ? parent.width - width - Style.space(3) : Style.space(3)
            color: root.bar.background
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              persisted.visualizerEnabled = !persisted.visualizerEnabled
              root.sendPlayerCommand("visualizer", persisted.visualizerEnabled)
            }
          }
        }

      }

      Rectangle {
        width: parent.width
        height: Style.space(1)
        color: Qt.alpha(root.bar.foreground, 0.12)
      }

      Text {
        visible: root.loadingStations
        textFormat: Text.PlainText
        text: strings.t("popup.loading")
        color: Qt.darker(root.bar.foreground, 1.3)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        visible: root.catalogWarning !== ""
        textFormat: Text.PlainText
        text: root.catalogWarning
        color: Qt.darker(root.bar.foreground, 1.3)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
        width: parent.width
      }

      Text {
        visible: root.catalogError !== ""
        textFormat: Text.PlainText
        text: root.catalogError
        color: root.bar.urgent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
        width: parent.width
      }

      ListView {
        id: stationList
        width: parent.width
        height: count > 0 ? Style.space(450) : 0
        clip: true
        spacing: Style.space(3)
        model: root.stationRows
        visible: count > 0
        boundsBehavior: Flickable.StopAtBounds

        delegate: Rectangle {
          required property var modelData
          width: stationList.width
          height: modelData.type === "header" ? Style.space(30) : Style.space(54)
          color: modelData.type === "header" ? "transparent"
            : (root.currentStation && root.currentStation.id === modelData.station.id
              ? Qt.alpha(Commons.Color.accent, 0.16)
              : Qt.alpha(root.bar.foreground, 0.035))
          radius: Style.spacing.labelGap

          Text {
            visible: modelData.type === "header"
            anchors.left: parent.left
            anchors.leftMargin: Style.space(4)
            anchors.bottom: parent.bottom
            textFormat: Text.PlainText
            text: modelData.title
            color: Qt.darker(root.bar.foreground, 1.2)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }

          Row {
            visible: modelData.type === "station"
            anchors.fill: parent
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(10)

            Image {
              id: stationThumbnail
              source: modelData.type === "station" ? modelData.station.image : ""
              visible: source !== ""
              width: visible ? Style.space(36) : 0
              height: visible ? Style.space(36) : 0
              sourceSize.width: 120
              sourceSize.height: 120
              fillMode: Image.PreserveAspectCrop
              asynchronous: true
              smooth: true
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              width: parent.width - stationThumbnail.width - stationInfo.implicitWidth
                - Style.space(20)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: modelData.type === "station"
                  ? (root.isFavorite(modelData.station.id) ? "★  " : "")
                    + modelData.station.title
                  : ""
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: modelData.type === "station" && root.currentStation
                  && root.currentStation.id === modelData.station.id
                elide: Text.ElideRight
              }

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: modelData.type === "station"
                  ? (modelData.station.description || modelData.station.genre || "")
                  : ""
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }
            }

            Column {
              id: stationInfo
              width: Math.max(bitrateLabel.implicitWidth, listeningTimeLabel.implicitWidth)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                id: bitrateLabel
                textFormat: Text.PlainText
                text: modelData.type === "station"
                  ? strings.t("popup.bitrate").arg(modelData.station.bitrate)
                  : ""
                color: Qt.darker(root.bar.foreground, 1.25)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignRight
                width: stationInfo.width
              }

              Text {
                id: listeningTimeLabel
                textFormat: Text.PlainText
                text: modelData.type === "station"
                  ? root.formatListeningTime(modelData.station.id)
                  : ""
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignRight
                width: stationInfo.width
              }
            }
          }

          MouseArea {
            anchors.fill: parent
            enabled: modelData.type === "station"
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: function(mouse) {
              if (mouse.button === Qt.RightButton) root.toggleFavorite(modelData.station)
              else {
                root.startStation(modelData.station)
                root.popupOpen = false
              }
            }
          }
        }
      }
    }

    Item {
      id: searchKeys
      width: 0
      height: 0
      focus: root.popupOpen
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        root.handleSearchKey(event)
        if (event.accepted) searchResetTimer.restart()
      }
    }
  }
}
