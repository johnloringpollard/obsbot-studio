"""Analyzer dispatch and lifecycle checks without a real device."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QObject, Signal, QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from obsbot_studio import ui
from obsbot_studio.effects import EffectSettings
from obsbot_studio.effects_panel import EffectsPanel
from obsbot_studio.analyzer import Result


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
        self.stops = 0
    def stop(self):
        self.stops += 1
        self.stopping = True


app = QApplication.instance() or QApplication([])
with tempfile.TemporaryDirectory() as directory:
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, directory)
    assert Path(QSettings("obsbot-studio", "portrait-tuning").fileName()).is_relative_to(directory)
    with patch.object(ui, 'Preview', Preview), patch.object(ui.MainWindow, 'request'), patch.object(ui.MainWindow, '_discover_audio'), patch.object(ui, 'EffectsPanel', lambda: EffectsPanel(settings_path=Path(directory)/'effects.json')):
        w = ui.MainWindow()
    w.command.disconnect()
    calls = []
    w.command.connect(lambda method, args: calls.append(method))
    w.snapshot = {'device': {'path': '/dev/fake'}, 'controls': [], 'tuning_undo': False}
    w._render()
    w._enabled()
    assert w.tune_button.isEnabled() and not w.undo_tuning_button.isEnabled()
    w.record_target = 'record.mp4'
    w.request('tune_exposure')
    assert not calls and not w.busy
    w.record_target = None
    w.effects = EffectSettings(gamma=1.2)
    w.request('tune_exposure')
    assert not calls and not w.busy
    w.effects = EffectSettings()
    w.preview.running = True
    target_args = []
    w.command.connect(lambda method, args: target_args.append(args))
    w.face_brightness_target.setValue(167)
    w.tune_button.click()
    assert w.busy and w.preview.stops == 1 and not calls
    assert not w.effects_panel.isEnabled()
    w._start_preview()  # Busy prevents reopening the device.
    w.preview.running = False
    w._preview_stopped()
    assert calls == ['tune_exposure'] and w.busy
    assert target_args == [[167]]
    assert QSettings('obsbot-studio', 'portrait-tuning').value('target', type=int) == 167
    state = dict(w.snapshot, tuning_undo=True, tuning_report='Exposure tuned.')
    w._finished('tune_exposure', state, '')
    assert not w.busy and w.undo_tuning_button.isEnabled() and w.tune_button.isEnabled()
    assert w.tuning_result.text() == 'Exposure tuned.'
    w.request('undo_tuning')
    assert calls[-1] == 'undo_tuning'
    w._finished('undo_tuning', dict(state, tuning_undo=False), '')
    w.preview.stopping = False
    w.effects_panel.gamma.setValue(120)
    assert w.effects_panel.timer.isActive()
    assert w.effects_panel.settings.gamma == 1.2 and w.effects.gamma == 1.0
    w.request('snapshot')
    assert calls[-1] == 'snapshot' and w.busy
    assert not w.effects_panel.timer.isActive()
    assert w.effects_panel.settings.gamma == w.effects.gamma == 1.2
    assert EffectsPanel(settings_path=Path(directory)/'effects.json').settings.gamma == 1.2
    w._finished('snapshot', w.snapshot, '')
    assert w.effects_panel.isEnabled() and w.effects.gamma == 1.2
    w.close()
    app.processEvents()
    assert not w.thread.isRunning()

worker = ui.CameraWorker()
class FakeCamera:
    def snapshot(self):
        return {'controls': []}
worker.camera = FakeCamera()
results = []
worker.finished.connect(lambda method, result, error: results.append((method, result, error)))
with patch.object(ui.analyzer, 'run', return_value=Result('Unchanged.')) as run:
    worker.execute('tune_exposure', [167])
    assert run.call_args.kwargs['options'].target == 167
    assert run.call_count == 1 and run.call_args.args == (worker.camera,)
assert results[-1][1]['tuning_report'] == 'Unchanged.' and not results[-1][2]
print('PASS analyzer UI recording/effects gates, preview handoff, worker dispatch, Undo state, pending effects on snapshot, thread shutdown')
