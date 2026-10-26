"""Native camera console. Camera commands execute on a single worker thread."""
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QProcess, Signal, Slot, QStandardPaths
from PySide6.QtGui import QImage, QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QScrollArea, QSlider, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget, QDialog, QPlainTextEdit, QTextBrowser,
)
from .camera import Camera, CameraError
from . import analyzer
from .preview import MODES, Preview
from .effects_panel import EffectsPanel

STYLE = """
QWidget { background: #202124; color: #efeff2; font-family: 'Noto Sans', sans-serif; font-size: 13px; }
QMainWindow { background: #17181a; }
QFrame#header { background: #242529; border-bottom: 1px solid #34353b; }
QLabel#brand { font-size: 20px; font-weight: 800; letter-spacing: 2px; }
QLabel#subtle { color: #9b9ca5; font-size: 12px; }
QLabel#preview { background: #111214; border: 1px solid #323338; border-radius: 12px; color: #85868f; font-size: 15px; }
QLabel#group { color: #f2f2f4; font-size: 14px; font-weight: 650; padding-top: 12px; }
QLabel#reason { color: #92939b; font-size: 11px; }
QPushButton { background: #34353a; border: 1px solid #414249; border-radius: 6px; padding: 9px 14px; }
QPushButton:hover { background: #45464d; }
QPushButton:pressed { background: #53545b; }
QPushButton#primary { background: #d92e40; border-color: #e34757; font-weight: 600; }
QPushButton#primary:hover { background: #eb4052; }
QPushButton:disabled, QComboBox:disabled, QSpinBox:disabled { color: #6e6f78; background: #292a2e; border-color: #33343a; }
QComboBox, QSpinBox { background: #2a2b30; border: 1px solid #46474e; border-radius: 5px; padding: 7px; }
QComboBox::drop-down { border: none; width: 23px; }
QComboBox QAbstractItemView { background: #303137; selection-background-color: #a72d3b; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #202124; color: #a7a8b0; min-width: 78px; padding: 14px 8px; border-bottom: 2px solid #35363b; }
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #ee4053; }
QScrollArea { border: none; }
QSlider { background: transparent; border: none; min-height: 28px; }
QSlider::groove:horizontal { height: 6px; background: #41434b; border: none; border-radius: 3px; }
QSlider::sub-page:horizontal { height: 6px; background: #ef3656; border: none; border-radius: 3px; }
QSlider::add-page:horizontal { height: 6px; background: #41434b; border: none; border-radius: 3px; }
QSlider::handle:horizontal { background: #f6f6f8; border: none; width: 20px; height: 20px; margin: -7px 0; border-radius: 10px; }
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::handle:horizontal:pressed { background: #ffdbe2; }
QSlider::sub-page:horizontal:disabled { background: #55565d; }
QSlider::handle:horizontal:disabled { background: #777984; }
QCheckBox { spacing: 10px; padding: 5px 0; }
QCheckBox::indicator { width: 30px; height: 17px; border-radius: 8px; background: #53545c; }
QCheckBox::indicator:checked { background: #e83e51; }
QCheckBox::indicator:disabled { background: #34353a; }
QScrollBar:vertical { width: 8px; background: #202124; }
QScrollBar::handle:vertical { background: #484951; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QToolTip { background: #414249; color: white; border: none; padding: 6px; }
"""


class CameraWorker(QObject):
    finished = Signal(str, object, str)
    progress = Signal(str)

    def __init__(self):
        super().__init__()
        self.camera = None

    @Slot(str, object)
    def execute(self, method, args):
        result, error = None, ""
        try:
            if method == "discover":
                result = Camera.discover()
            elif method == "connect":
                self.camera = None
                self.camera = Camera(args[0])
                result = self.camera.snapshot()
            elif self.camera is not None:
                if method in ("tune_exposure", "undo_tuning"):
                    report = analyzer.run(self.camera, progress=self.progress.emit) if method == "tune_exposure" else analyzer.undo(self.camera)
                    result = self.camera.snapshot()
                    result["tuning_report"] = report.message
                else:
                    result = getattr(self.camera, method)(*args)
            else:
                raise CameraError("Select a camera first.")
            if self.camera is not None and isinstance(result, dict) and "controls" in result:
                result["tuning_undo"] = analyzer.undo_available(self.camera) if hasattr(self.camera, "state_dir") else False

        except Exception as exc:
            error = str(exc)
            logging.exception("Camera operation %s failed", method)
            if self.camera is not None and method != "discover":
                try:
                    result = self.camera.snapshot()
                    result["tuning_undo"] = analyzer.undo_available(self.camera) if hasattr(self.camera, "state_dir") else False
                except Exception:
                    pass
        self.finished.emit(method, result, error)


class PreviewLabel(QLabel):
    def __init__(self):
        super().__init__("Preview is off\n\nStart preview to see your camera")
        self.setObjectName("preview")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 180)
        self.image = QImage()

    def show_image(self, image):
        self.image = image.copy()
        self._scale()

    def _scale(self):
        if not self.image.isNull():
            self.setPixmap(QPixmap.fromImage(self.image).scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        self._scale()
        super().resizeEvent(event)


class Teleprompter(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Teleprompter · reading aid")
        self.resize(800, 600)
        layout = QVBoxLayout(self)
        note = QLabel("This window is a reading aid. Its text is not included in preview, snapshots or recordings.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Paste or type your script here…")
        self.editor.setObjectName("teleprompter_script")
        layout.addWidget(self.editor, 1)
        self.reader = QTextBrowser()
        self.reader.hide()
        layout.addWidget(self.reader, 1)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Font size"))
        self.font_size = QSpinBox()
        self.font_size.setRange(18, 96)
        self.font_size.setValue(36)
        self.font_size.valueChanged.connect(self._font)
        controls.addWidget(self.font_size)
        controls.addWidget(QLabel("Speed"))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(1, 10)
        self.speed.setValue(3)
        controls.addWidget(self.speed, 1)
        self.play = QPushButton("Start")
        self.play.clicked.connect(self._toggle)
        controls.addWidget(self.play)
        self.reset = QPushButton("Reset / edit")
        self.reset.clicked.connect(self._reset)
        controls.addWidget(self.reset)
        layout.addLayout(controls)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._scroll)
        self._font()

    def _font(self):
        font = self.reader.font()
        font.setPointSize(self.font_size.value())
        self.reader.setFont(font)

    def _toggle(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play.setText("Resume")
            return
        if not self.editor.isHidden():
            if not self.editor.toPlainText().strip():
                self.editor.setFocus()
                return
            self.reader.setPlainText(self.editor.toPlainText())
            self.editor.hide()
            self.reader.show()
            self.reader.verticalScrollBar().setValue(0)
        self.timer.start()
        self.play.setText("Pause")

    def _scroll(self):
        bar = self.reader.verticalScrollBar()
        bar.setValue(bar.value() + self.speed.value())
        if bar.value() == bar.maximum():
            self.timer.stop()
            self.play.setText("At end · reset to replay")

    def _reset(self):
        self.timer.stop()
        self.reader.verticalScrollBar().setValue(0)
        self.reader.hide()
        self.editor.show()
        self.play.setText("Start")

    def closeEvent(self, event):
        self.timer.stop()
        self.play.setText("Resume" if self.editor.isHidden() else "Start")
        event.accept()


class MainWindow(QMainWindow):
    command = Signal(str, object)

    def __init__(self, start_preview=False):
        super().__init__()
        self.setWindowTitle("OBSBOT Studio")
        self.resize(1240, 850)
        self.setMinimumSize(1020, 800)
        self.snapshot = None
        self.busy = False
        self.pending = None
        self.preview_wanted = start_preview
        self.closing = False
        self.export_path = None
        self.record_target = None
        self.record_finishing = False
        self.preview_sync_pending = False
        self.accept_frames = False
        self.mode_without_effects = None
        self.teleprompter = None
        self.preview = Preview(self)
        self.preview.frame.connect(self._frame)
        self.preview.error.connect(self._preview_error)
        self.preview.stopped.connect(self._preview_stopped)
        self.preview.started.connect(self._capture_started)
        self.preview.recording_finished.connect(self._recording_finished)
        self.thread = QThread(self)
        self.worker = CameraWorker()
        self.worker.moveToThread(self.thread)
        self.command.connect(self.worker.execute)
        self.worker.finished.connect(self._finished)
        self.worker.progress.connect(self._tuning_progress)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        self._build()
        self.audio_process = QProcess(self)
        self.audio_process.finished.connect(self._audio_discovered)
        self.audio_process.errorOccurred.connect(self._audio_error)
        self.audio_timeout = QTimer(self)
        self.audio_timeout.setSingleShot(True)
        self.audio_timeout.timeout.connect(self.audio_process.kill)
        self._discover_audio()
        self.request("discover")

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 12)
        header = QFrame()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(24, 16, 24, 16)
        brand = QLabel("OBSBOT  /  STUDIO")
        brand.setObjectName("brand")
        row.addWidget(brand)
        row.addStretch()
        self.devices = QComboBox()
        self.devices.setObjectName("devices")
        self.devices.setMinimumWidth(240)
        self.devices.activated.connect(self._select_device)
        row.addWidget(self.devices)
        self.refresh = QPushButton("Refresh")
        self.refresh.setObjectName("refresh")
        self.refresh.clicked.connect(lambda: self.request("snapshot") if self.snapshot else self.request("discover"))
        row.addWidget(self.refresh)
        layout.addWidget(header)
        body = QHBoxLayout()
        body.setContentsMargins(24, 14, 24, 0)
        body.setSpacing(22)
        left = QVBoxLayout()
        title = QLabel("Camera preview")
        title.setObjectName("group")
        left.addWidget(title)
        self.video = PreviewLabel()
        left.addWidget(self.video, 1)
        capture = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.setObjectName("preview_mode")
        self.mode.addItems(MODES)
        self.mode.activated.connect(self._mode_changed)
        capture.addWidget(self.mode)
        capture.addStretch()
        self.preview_button = QPushButton("Start preview")
        self.preview_button.setObjectName("primary")
        self.preview_button.clicked.connect(self._toggle_preview)
        capture.addWidget(self.preview_button)
        self.photo = QPushButton("Snapshot")
        self.photo.setObjectName("save_snapshot")
        self.photo.setEnabled(False)
        self.photo.clicked.connect(self._save_photo)
        capture.addWidget(self.photo)
        left.addLayout(capture)
        info = QLabel("MJPEG capture · Preview is displayed at up to 30 fps\nSnapshots save the displayed frame. Fast encoding uses larger files; 4K and high frame rates depend on CPU capacity.")
        info.setObjectName("subtle")
        info.setWordWrap(True)
        left.addWidget(info)
        recording = QHBoxLayout()
        self.record_mode = QComboBox()
        self.record_mode.setObjectName("record_mode")
        self.record_mode.addItem("Normal speed", False)
        self.record_mode.addItem("Slow motion · 30 fps playback", True)
        self.record_mode.currentIndexChanged.connect(self._enabled)
        recording.addWidget(self.record_mode)
        recording.addStretch()
        self.record_button = QPushButton("Record video")
        self.record_button.setObjectName("record_video")
        self.record_button.clicked.connect(self._toggle_recording)
        recording.addWidget(self.record_button)
        left.addLayout(recording)
        audio_row = QHBoxLayout()
        audio_row.addWidget(QLabel("Microphone"))
        self.audio_source = QComboBox()
        self.audio_source.setObjectName("audio_source")
        self.audio_source.setMinimumWidth(190)
        self.audio_source.setMaximumWidth(350)
        self.audio_source.addItem("Off · video only", None)
        audio_row.addWidget(self.audio_source, 1)
        self.audio_refresh = QPushButton("Refresh inputs")
        self.audio_refresh.setObjectName("refresh_audio")
        self.audio_refresh.clicked.connect(self._discover_audio)
        audio_row.addWidget(self.audio_refresh)
        left.addLayout(audio_row)
        self.audio_note = QLabel("Choose a microphone explicitly. Slow-motion recordings are silent.")
        self.audio_note.setObjectName("subtle")
        self.audio_note.setWordWrap(True)
        left.addWidget(self.audio_note)
        self.record_result = QLabel("Recordings save to Videos / OBSBOT Studio")
        self.record_result.setObjectName("subtle")
        self.record_result.setWordWrap(True)
        self.record_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left.addWidget(self.record_result)
        local_title = QLabel("Local presets")
        local_title.setObjectName("group")
        left.addWidget(local_title)
        presets = QHBoxLayout()
        self.preset_widgets = []
        for slot in range(1, 5):
            box = QVBoxLayout()
            label = QLabel(f"Preset {slot}")
            label.setAlignment(Qt.AlignCenter)
            box.addWidget(label)
            recall = QPushButton("Recall")
            recall.setObjectName(f"recall_preset_{slot}")
            recall.clicked.connect(lambda checked=False, n=slot: self.request("recall_preset", [n]))
            save = QPushButton("Save")
            save.setObjectName(f"save_preset_{slot}")
            save.clicked.connect(lambda checked=False, n=slot: self.request("save_preset", [n]))
            self.preset_widgets.extend((recall, save))
            actions = QHBoxLayout()
            actions.addWidget(recall)
            actions.addWidget(save)
            box.addLayout(actions)
            presets.addLayout(box)
        left.addLayout(presets)
        preset_note = QLabel("Presets exclude sleep, auto-sleep and red/blue channel gain restoration.")
        preset_note.setObjectName("subtle")
        preset_note.setWordWrap(True)
        left.addWidget(preset_note)
        left.addSpacing(10)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settings_tabs")
        self.tabs.setFixedWidth(430)
        self.pages = {}
        self.scrolls = {}
        for section in ("Console", "Image", "More"):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(12, 6, 14, 16)
            page_layout.setSpacing(14)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, section)
            self.pages[section] = page_layout
            self.scrolls[section] = scroll
        self.effects_panel = EffectsPanel()
        self.effects = self.effects_panel.settings
        self.effects_panel.changed.connect(self._effects_changed)
        effects_scroll = QScrollArea()
        effects_scroll.setWidgetResizable(True)
        effects_scroll.setWidget(self.effects_panel)
        self.tabs.insertTab(2, effects_scroll, "Effects")
        self._effects_mode()
        right.addWidget(self.tabs)
        self.export = QPushButton("Export camera settings…")
        self.export.setObjectName("export_settings")
        self.export.clicked.connect(self._export)
        right.addWidget(self.export)
        body.addLayout(right)
        layout.addLayout(body, 1)
        self.status = QLabel("Looking for cameras…")
        self.status.setObjectName("subtle")
        self.status.setWordWrap(True)
        self.status.setContentsMargins(24, 8, 24, 0)
        layout.addWidget(self.status)

    def _status(self, text):
        self.status.setText(text)

    def _tuning_progress(self, message):
        self.tuning_message = message
        if hasattr(self, "tuning_result"):
            self.tuning_result.setText(message)
        self._status(message)

    def request(self, method, args=None):
        if self.busy or self.closing or self.record_target or self.preview.recording_path or self.record_finishing:
            return
        self.effects_panel.flush()
        if self.busy or self.closing or self.record_target or self.preview.recording_path or self.record_finishing:
            return
        if method == "tune_exposure":
            if self.effects.active:
                self._tuning_progress("Turn off Effects before tuning exposure.")
                return
        self.busy = True
        self.pending = (method, args or [])
        self._enabled()
        self._status("Reading camera…" if method in ("discover", "connect", "snapshot") else "Updating camera…")
        if method in ("tune_exposure", "undo_tuning"):
            self._tuning_progress("Measuring exposure. Hold still…" if method == "tune_exposure" else "Restoring original exposure…")
        sleeping = method == "apply" and bool(args) and args[0] == "sleep" and bool(args[1])
        if sleeping:
            self.preview_wanted = False
            self.preview_button.setText("Start preview")
        if self.preview.running and (method in ("connect", "discover", "tune_exposure", "undo_tuning") or sleeping):
            self.preview.stop()
        else:
            self._dispatch()

    def _dispatch(self):
        if self.pending:
            method, args = self.pending
            self.pending = None
            self.command.emit(method, args)

    def _preview_stopped(self):
        self.accept_frames = False
        self.photo.setEnabled(False)
        self.record_finishing = False
        self._enabled()
        if self.closing:
            QTimer.singleShot(0, self.close)
            return
        if self.pending:
            self._dispatch()
        elif not self.busy and self.preview_wanted and not self.closing:
            self._start_preview()

    def _finished(self, method, result, error):
        self.busy = False
        if method == "discover":
            self.devices.clear()
            for device in result or []:
                self.devices.addItem(device["name"], device["path"])
            if self.devices.count():
                self._select_device(0)
                return
            self._status(error or "No supported camera found. Connect your camera, then refresh.")
        else:
            if error and result is None:
                self.snapshot = None
            if isinstance(result, dict) and "controls" in result:
                self.snapshot = result
                if "tuning_report" in result:
                    self.tuning_message = result["tuning_report"]
                self._render()
            if method == "export_snapshot" and not error and self.export_path:
                try:
                    Path(self.export_path).write_text(json.dumps(result, indent=2) + "\n")
                except OSError as exc:
                    error = str(exc)
                self.export_path = None
            self._status(error or (result.get("tuning_report") if isinstance(result, dict) else None) or ("Settings exported." if method == "export_snapshot" else "Camera ready · Settings read from device"))
        self._enabled()
        if self.preview_wanted and self.snapshot:
            self._start_preview()

    def _select_device(self, index):
        self.snapshot = None
        self.tuning_message = ""
        self.video.image = QImage()
        self.video.clear()
        self.video.setText("Preview is off")
        self.request("connect", [self.devices.itemData(index)])

    def _enabled(self):
        recording = bool(self.record_target or self.preview.recording_path or self.record_finishing)
        ready = self.snapshot is not None and not self.busy and not recording
        self.tabs.setEnabled(not recording)
        for scroll in self.scrolls.values():
            scroll.setEnabled(ready)
        self.effects_panel.setEnabled(not recording and not self.busy)
        if hasattr(self, "tune_button"):
            self.tune_button.setEnabled(ready and not self.effects.active)
            self.undo_tuning_button.setEnabled(ready and self.snapshot.get("tuning_undo", False))
        self.devices.setEnabled(not self.busy and not recording)
        self.refresh.setEnabled(not self.busy and not recording)
        self.preview_button.setEnabled(ready)
        self.mode.setEnabled(ready and not self.effects.active)
        self.export.setEnabled(ready)
        self.record_mode.setEnabled(ready and not self.effects.active)
        self.audio_source.setEnabled(ready and not bool(self.record_mode.currentData()))
        self.audio_refresh.setEnabled(ready and not bool(self.record_mode.currentData()))
        self.audio_source.setToolTip("Slow motion is silent; the selected microphone is ignored." if self.record_mode.currentData() else "Audio is recorded only from the input you select.")
        self.record_button.setEnabled(self.snapshot is not None and not self.busy and not self.record_finishing)
        self.record_button.setText("Saving recording…" if self.record_finishing else "Stop recording" if recording else "Record video")
        for widget in self.preset_widgets:
            widget.setEnabled(ready)

    def _render(self):
        positions = {section: self.scrolls[section].verticalScrollBar().value() for section, page in self.pages.items()}
        for page in self.pages.values():
            while page.count():
                item = page.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        explanation = QLabel("Tune exposure once for the current lighting. Keep one face still in view, enable auto exposure, and turn off Effects. Only exposure compensation can change; other camera settings stay as they are.")
        explanation.setWordWrap(True)
        self.pages["Image"].addWidget(explanation)
        self.tune_button = QPushButton("Tune exposure")
        self.tune_button.setObjectName("tune_exposure")
        self.tune_button.clicked.connect(lambda: self.request("tune_exposure"))
        self.pages["Image"].addWidget(self.tune_button)
        self.undo_tuning_button = QPushButton("Undo tuning")
        self.undo_tuning_button.setObjectName("undo_tuning")
        self.undo_tuning_button.clicked.connect(lambda: self.request("undo_tuning"))
        self.pages["Image"].addWidget(self.undo_tuning_button)
        self.tuning_result = QLabel(getattr(self, "tuning_message", ""))
        self.tuning_result.setWordWrap(True)
        self.pages["Image"].addWidget(self.tuning_result)
        groups = {}
        for control in self.snapshot.get("controls", []):
            section = control.get("section", "More")
            page = self.pages.get(section, self.pages["More"])
            group = control.get("group", "Camera settings")
            if groups.get(section) != group:
                heading = QLabel(group)
                heading.setObjectName("group")
                page.addWidget(heading)
                groups[section] = group
            page.addWidget(self._control(control))
        teleprompter = QPushButton("Open teleprompter…")
        teleprompter.setObjectName("open_teleprompter")
        teleprompter.clicked.connect(self._open_teleprompter)
        self.pages["More"].addWidget(teleprompter)
        for section, page in self.pages.items():
            if not page.count():
                page.addWidget(QLabel("No controls reported by this camera."))
            page.addStretch()
            bar = self.scrolls[section].verticalScrollBar()
            QTimer.singleShot(0, lambda b=bar, p=positions[section]: b.setValue(p))

    def _open_teleprompter(self):
        if self.teleprompter is None:
            self.teleprompter = Teleprompter(self)
        self.teleprompter.show()
        self.teleprompter.raise_()
        self.teleprompter.activateWindow()

    def _control(self, control):
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        key = str(control["id"])
        label = control.get("label", key)
        kind = control.get("kind", "unavailable")
        enabled = control.get("enabled", True) and kind != "unavailable"
        value = control.get("value")
        if kind == "bool":
            widget = QCheckBox(label)
            widget.setChecked(bool(value))
            widget.toggled.connect(lambda v, k=key: self.request("apply", [k, v]))
        elif kind in ("int", "integer", "slider"):
            layout.addWidget(QLabel(label))
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Horizontal)
            slider.setObjectName(f"control_{key}_slider")
            spin = QSpinBox()
            spin.setObjectName(f"control_{key}")
            spin.setFixedWidth(90)
            low, high = int(control.get("min", 0)), int(control.get("max", 100))
            step = max(1, int(control.get("step", 1)))
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setValue(int(value or 0))
            slider.setRange(0, (high - low) // step)
            slider.setValue((int(value or 0) - low) // step)
            slider.valueChanged.connect(lambda v, s=spin, lo=low, inc=step: s.setValue(lo + v * inc))
            spin.valueChanged.connect(lambda v, s=slider, lo=low, inc=step: s.setValue((v - lo) // inc))
            def submit(k=key, s=spin, lo=low, hi=high, inc=step, old=value):
                accepted = max(lo, min(hi, lo + round((s.value() - lo) / inc) * inc))
                s.setValue(accepted)
                if accepted != old:
                    self.request("apply", [k, accepted])
            slider.sliderReleased.connect(submit)
            slider.actionTriggered.connect(lambda action, s=slider, fn=submit: QTimer.singleShot(0, fn) if not s.isSliderDown() else None)
            spin.editingFinished.connect(submit)
            row.addWidget(slider, 1)
            row.addWidget(spin)
        elif kind in ("select", "menu"):
            layout.addWidget(QLabel(label))
            widget = QComboBox()
            for option in control.get("options", []):
                widget.addItem(str(option["label"]), option["value"])
            widget.setCurrentIndex(widget.findData(value))
            widget.activated.connect(lambda index, w=widget, k=key: self.request("apply", [k, w.itemData(index)]))
        elif kind == "action":
            widget = QPushButton(label)
            widget.clicked.connect(lambda checked=False, k=key: self.request("apply", [k, True]))
        else:
            widget = QLabel(label)
        if kind not in ("int", "integer", "slider"):
            widget.setObjectName(f"control_{key}")
        widget.setEnabled(enabled)
        widget.setToolTip(control.get("reason", ""))
        layout.addWidget(widget)
        if control.get("reason"):
            reason = QLabel(control["reason"])
            reason.setObjectName("reason")
            reason.setWordWrap(True)
            layout.addWidget(reason)
        return wrapper

    def _clear_preview(self, text="Starting preview…"):
        self.accept_frames = False
        self.video.image = QImage()
        self.video.clear()
        self.video.setText(text)
        self.photo.setEnabled(False)

    def _effects_mode(self):
        if self.effects.active:
            if self.mode_without_effects is None:
                self.mode_without_effects = (self.mode.currentIndex(), self.record_mode.currentIndex())
            self.mode.setCurrentText("720p · 30 fps")
            self.record_mode.blockSignals(True)
            self.record_mode.setCurrentIndex(0)
            self.record_mode.blockSignals(False)
        elif self.mode_without_effects is not None:
            mode, recording = self.mode_without_effects
            self.mode_without_effects = None
            self.mode.setCurrentIndex(mode)
            self.record_mode.blockSignals(True)
            self.record_mode.setCurrentIndex(recording)
            self.record_mode.blockSignals(False)

    def _effects_changed(self, settings):
        if self.record_target or self.preview.recording_path or self.record_finishing:
            return
        if settings == self.effects:
            return
        was_slow_motion = bool(self.record_mode.currentData())
        self.effects = settings
        self._effects_mode()
        if self.effects.active and was_slow_motion:
            self._status("Effects use normal-speed 720p · 30 fps. Turn off effects to restore slow motion.")
        self._enabled()
        self._clear_preview("Starting effects…" if self.preview_wanted else "Preview is off")
        if self.preview.running:
            self.preview.stop()
        elif self.preview_wanted:
            self._start_preview()

    def _start_preview(self):
        if self.snapshot and not self.busy and not self.closing:
            self.preview_button.setText("Stop preview")
            if not self.preview.running:
                self._clear_preview()
            self.preview.start(self.snapshot["device"]["path"], self.mode.currentText(), self.record_target, bool(self.record_mode.currentData()), None if self.record_mode.currentData() else self.audio_source.currentData(), effects=self.effects)

    def _toggle_preview(self):
        self.effects_panel.flush()
        self.preview_wanted = not self.preview_wanted
        if self.preview_wanted:
            self._start_preview()
        else:
            self.preview_button.setText("Start preview")
            self.preview.stop()
            self._status("Preview stopped · Camera released")

    def _mode_changed(self):
        if self.preview.running:
            self.preview.stop()

    def _preview_error(self, message):
        self._clear_preview("Preview unavailable")
        self.record_target = None
        self.record_finishing = False
        self._enabled()
        self.preview_wanted = False
        self.preview_button.setText("Start preview")
        self._status(message)

    def _discover_audio(self):
        if self.audio_process.state() != QProcess.NotRunning:
            return
        self.audio_refresh.setEnabled(False)
        self.audio_note.setText("Looking for microphone inputs…")
        self.audio_process.start("pactl", ["-f", "json", "list", "sources"])
        self.audio_timeout.start(5000)

    def _audio_error(self, error):
        if error == QProcess.FailedToStart:
            self.audio_timeout.stop()
            self.audio_note.setText("Microphone discovery unavailable: install pactl with PulseAudio or PipeWire audio support. Video-only recording is available.")
            self._enabled()

    def _audio_discovered(self, code, status):
        self.audio_timeout.stop()
        selected = self.audio_source.currentData()
        self.audio_source.clear()
        self.audio_source.addItem("Off · video only", None)
        try:
            if code:
                detail = bytes(self.audio_process.readAllStandardError()).decode("utf-8", "replace").strip()[-300:]
                raise ValueError(detail or "Audio server did not respond.")
            sources = json.loads(bytes(self.audio_process.readAllStandardOutput()))
            if not isinstance(sources, list):
                raise ValueError("Audio server returned an invalid source list.")
            for source in sources:
                name = source.get("name")
                if isinstance(name, str) and not name.endswith(".monitor"):
                    self.audio_source.addItem(str(source.get("description") or name), name)
            if selected is not None:
                self.audio_source.setCurrentIndex(max(0, self.audio_source.findData(selected)))
            self.audio_note.setText("Choose an input explicitly. Slow motion is silent." if self.audio_source.count() > 1 else "No microphone inputs found. Video-only recording is available.")
        except (ValueError, TypeError, AttributeError) as exc:
            self.audio_note.setText(f"Microphone discovery unavailable: {exc}")
        self._enabled()

    def _capture_started(self):
        self.accept_frames = True
        self.preview_sync_pending = True
        if self.preview.recording_path:
            mode = "slow motion" if self.record_mode.currentData() else "normal speed"
            audio = "Video only" if self.record_mode.currentData() or not self.audio_source.currentData() else self.audio_source.currentText()
            self._status(f"Recording {mode} · {audio} · {self.preview.recording_path}")
        else:
            self._status("Effects output 720p · 30 fps" if self.effects.active else "Live preview · display capped at 30 fps")
        self._enabled()

    def _toggle_recording(self):
        self.effects_panel.flush()
        if self.record_target or self.preview.recording_path:
            self.record_target = None
            self.record_finishing = True
            self._enabled()
            self._status("Saving recording. Please wait…")
            self.preview.stop()
            return
        if self.effects.active and self.record_mode.currentData():
            self._status("Turn off effects to record slow motion.")
            return
        if self.record_mode.currentData() and MODES[self.mode.currentText()][2] <= 30:
            self._status("Choose a 60 or 120 fps capture mode for slow motion.")
            return
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.MoviesLocation)) / "OBSBOT Studio"
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._status(str(exc))
            return
        self.record_target = str(directory / f"recording-{datetime.now():%Y%m%d-%H%M%S-%f}.mp4")
        self.preview_wanted = True
        self._enabled()
        if self.preview.running:
            self.preview.stop()
        else:
            self._start_preview()

    def _recording_finished(self, path, success):
        self.record_target = None
        message = f"Recording saved to {path}" if success else f"Recording interrupted. Check for a recoverable file at {path}"
        self.record_result.setText(message)
        self._status(message)

    def _frame(self, image):
        if not self.accept_frames or self.preview.stopping:
            return
        if self.preview_sync_pending and not self.busy and not (self.record_target or self.preview.recording_path):
            self.preview_sync_pending = False
            self.request("snapshot")
        self.video.show_image(image)
        self.photo.setEnabled(True)

    def _save_photo(self):
        if self.video.image.isNull():
            return
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)) / "OBSBOT Studio"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"snapshot-{datetime.now():%Y%m%d-%H%M%S-%f}.png"
            if not self.video.image.save(str(path), "PNG"):
                raise OSError("Could not save snapshot")
            self._status(f"Snapshot saved to {path}")
        except OSError as exc:
            self._status(str(exc))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export camera settings", "obsbot-settings.json", "JSON (*.json)")
        if path:
            self.export_path = path
            self.request("export_snapshot")

    def closeEvent(self, event):
        self.effects_panel.flush()
        self.closing = True
        self.preview_wanted = False
        if self.pending is not None:
            self.pending = None
            self.busy = False
        self.audio_timeout.stop()
        if self.audio_process.state() != QProcess.NotRunning:
            self.audio_process.kill()
            self.audio_process.waitForFinished(1000)
        if self.preview.running:
            if not self.preview.stopping:
                self.preview.stop()
            event.ignore()
            self._status("Finishing capture before closing…")
            return
        if self.busy:
            event.ignore()
            self._status("Waiting for the camera operation to finish before closing…")
            QTimer.singleShot(200, self.close)
            return
        self.thread.quit()
        self.thread.wait()
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Native Linux OBSBOT camera console")
    parser.add_argument("--preview", action="store_true", help="Start the camera preview on launch")
    parser.add_argument("--tab", choices=("Console", "Image", "Effects", "More"), default="Console", help="Open a settings tab")
    parser.add_argument("--screenshot", help="Save a UI screenshot, then quit")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("OBSBOT Studio")
    app.setDesktopFileName("obsbot-studio")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.svg"))))
    app.setOrganizationName("Local")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    logging.basicConfig(level=logging.INFO)
    previous_hook = sys.excepthook
    def report_error(kind, value, traceback):
        logging.error("Unhandled UI error", exc_info=(kind, value, traceback))
        window._status(f"Unexpected error: {value}")
    sys.excepthook = report_error
    window = MainWindow(args.preview)
    window.tabs.setCurrentIndex(next(i for i in range(window.tabs.count()) if window.tabs.tabText(i) == args.tab))
    window.show()
    if args.screenshot:
        def capture():
            if window.busy:
                QTimer.singleShot(100, capture)
                return
            window.grab().save(args.screenshot)
            window.close()
        QTimer.singleShot(800, capture)
    result = app.exec()
    sys.excepthook = previous_hook
    return result


if __name__ == "__main__":
    raise SystemExit(main())
