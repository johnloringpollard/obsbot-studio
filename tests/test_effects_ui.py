"""Exercise effects UI without opening camera, microphone, or capture processes."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from obsbot_studio.effects import EffectSettings
from obsbot_studio.effects_panel import EffectsPanel

fake = types.ModuleType("obsbot_studio.camera")
fake.Camera = type("Camera", (), {})
fake.CameraError = RuntimeError
sys.modules[fake.__name__] = fake
from obsbot_studio import ui

class Preview(QObject):
    frame = Signal(QImage)
    error = Signal(str)
    stopped = Signal()
    started = Signal()
    recording_finished = Signal(str, bool)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.stopping = False
        self.recording_path = None
        self.starts = []
        self.stops = 0
    def start(self, *args, **kwargs):
        if self.running:
            return
        self.starts.append((args, kwargs))
        self.running = True
        self.stopping = False
        self.recording_path = args[2]
        self.started.emit()
    def stop(self):
        self.stops += 1
        self.stopping = True
    def finish(self):
        self.running = False
        self.stopping = False
        self.recording_path = None
        self.stopped.emit()

app = QApplication.instance() or QApplication([])
def wait(ms=300):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(.005)

with tempfile.TemporaryDirectory() as directory:
    settings_path = Path(directory) / "effects.json"
    panel = EffectsPanel(settings_path=settings_path)
    events = []
    panel.changed.connect(events.append)
    panel.background.setCurrentIndex(panel.background.findData("blur"))
    panel.blur.setValue(71)
    panel.blur.setValue(72)
    assert not events
    wait()
    assert len(events) == 1 and events[0].blur == 72
    assert EffectsPanel(settings_path=settings_path).settings == panel.settings
    panel.gamma.setValue(135)
    panel.flush()
    assert panel.settings.gamma == 1.35
    with patch.object(ui.QFileDialog, 'getOpenFileName', return_value=('', '')):
        panel.background.setCurrentIndex(panel.background.findData('image'))
    assert panel.settings.background == 'blur' and panel.background.currentData() == 'blur'
    panel.reset.click()
    panel.flush()
    assert panel.settings == EffectSettings()
    assert panel.gamma.value() == 100 and panel.overlay_scale.value() == 20
    settings_path.write_text('{invalid')
    assert "could not be loaded" in EffectsPanel(settings_path=settings_path).message.text()
    settings_path.unlink()

    with patch.object(ui, "Preview", Preview), patch.object(ui.MainWindow, "request"), patch.object(ui.MainWindow, "_discover_audio"), patch.object(ui, "EffectsPanel", lambda: EffectsPanel(settings_path=settings_path)):
        w = ui.MainWindow()
        w.snapshot = {"device": {"path": "/dev/fake"}, "controls": []}
        w._enabled()
        assert not w.preview.starts
        assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ['Console', 'Image', 'Effects', 'More']
        w.mode.setCurrentText('1080p · 120 fps')
        w.record_mode.setCurrentIndex(1)
        w.effects_panel.background.setCurrentIndex(w.effects_panel.background.findData('blur'))
        w.effects_panel.flush()
        assert w.mode.currentText() == '720p · 30 fps'
        assert not w.mode.isEnabled() and not w.record_mode.isEnabled()
        assert w.record_mode.currentData() is False
        assert not w.preview.starts
        w._render()
        assert w.effects_panel.settings.background == 'blur'
        w._toggle_preview()
        args, kwargs = w.preview.starts[-1]
        assert args[1] == '720p · 30 fps' and kwargs['effects'].background == 'blur'
        frame = QImage(20, 20, QImage.Format_RGB32)
        frame.fill(0xff408080)
        w.preview.frame.emit(frame)
        assert w.photo.isEnabled() and not w.video.image.isNull()
        w.effects_panel.blur.setValue(50)
        w.effects_panel.flush()
        assert w.preview.stopping and not w.photo.isEnabled() and w.video.image.isNull()
        w.preview.frame.emit(frame)
        assert w.video.image.isNull()
        w.preview.finish()
        w.preview.frame.emit(frame)
        assert w.photo.isEnabled()
        w.record_target = '/tmp/fake.mp4'
        w._enabled()
        assert not w.effects_panel.isEnabled() and not w.effects_panel.gamma.isEnabled()
        old = w.effects
        w.effects_panel._update(gamma=1.5)
        w._effects_changed(EffectSettings(gamma=1.5))
        assert w.effects == old and w.effects_panel.settings == old
        w.record_target = None
        w._enabled()
        w.effects_panel.reset.click()
        w.effects_panel.flush()
        assert w.mode.currentText() == '1080p · 120 fps' and w.mode.isEnabled()
        assert w.record_mode.currentData() is True and w.record_mode.isEnabled()
        w.preview.finish()
        assert w.preview.starts[-1][0][1] == '1080p · 120 fps'
        w._preview_error('Processor unavailable')
        assert w.video.image.isNull() and not w.photo.isEnabled()
        w.preview.frame.emit(frame)
        assert w.video.image.isNull()
        w._open_teleprompter()
        prompt = w.teleprompter
        prompt.editor.setPlainText("A line to read.\n" * 200)
        prompt.play.click()
        wait(120)
        assert prompt.timer.isActive() and prompt.editor.isHidden()
        assert prompt.reader.verticalScrollBar().value() > 0
        prompt.play.click()
        assert not prompt.timer.isActive()
        prompt.font_size.setValue(48)
        assert prompt.reader.font().pointSize() == 48
        prompt.reset.click()
        assert not prompt.editor.isHidden() and not prompt.timer.isActive()
        assert prompt.reader.verticalScrollBar().value() == 0
        prompt.play.click()
        prompt.close()
        assert not prompt.timer.isActive()
        w.preview.running = False
        w.close()
        app.processEvents()
        assert not w.thread.isRunning()
print('PASS effects persistence, slider debounce, gamma, cancelled image choice, reset, tab preservation, preview propagation, 720p limit, high-fps restoration, recording lock, stale frame rejection, teleprompter scroll/pause/reset/close')
