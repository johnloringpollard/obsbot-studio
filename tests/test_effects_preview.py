"""Exercise Qt's actual effects child process and recording completion."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
import subprocess
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from obsbot_studio.preview import Preview
from obsbot_studio.effects import EffectSettings

app = QCoreApplication([])
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / 'source.mkv'
    output = Path(directory) / 'processed.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30', '-t', '0.6', '-c:v', 'ffv1', str(source)], check=True)
    preview = Preview()
    frames, saved = [], []
    preview.frame.connect(lambda frame: frames.append(frame.copy()))
    preview.recording_finished.connect(lambda path, success: saved.append((path, success)))
    real_start = preview.process.start
    def start_file(program, args):
        assert program == sys.executable
        assert args[:2] == ['-m', 'obsbot_studio.effects_capture']
        real_start(program, args + ['--input', str(source)])
    preview.process.start = start_file
    preview.start('/dev/not-accessed', '720p · 30 fps', str(output), effects=EffectSettings(filter='mono'))
    end = time.monotonic() + 20
    while preview.running and time.monotonic() < end:
        app.processEvents()
        time.sleep(.005)
    assert not preview.running, preview.diagnostics
    assert saved == [(str(output), True)], (saved, preview.diagnostics)
    assert frames and frames[-1].width() == 1280
    pixel = frames[-1].pixelColor(500, 300)
    assert abs(pixel.red() - pixel.blue()) <= 3
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True)
    print('PASS Qt effects child emits processed frames, finalizes MP4, fully decodes, releases process')
