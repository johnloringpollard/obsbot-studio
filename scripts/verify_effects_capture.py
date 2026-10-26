"""Explicit live Tiny 3 effects capture; saves private local verification artifacts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QTimer
from obsbot_studio.camera import Camera
from obsbot_studio.effects import EffectSettings
from obsbot_studio.preview import Preview

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds', type=int, default=12)
parser.add_argument('--audio', default=None)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
directory = root / 'evidence'
directory.mkdir(exist_ok=True)
output = directory / f'effects-live-{time.time_ns()}.mp4'
app = QCoreApplication([])
preview = Preview()
report = {'file': str(output), 'errors': [], 'frames': 0, 'finished': []}
started = time.monotonic()
first = None
last = None

def frame(image):
    global first, last
    now = time.monotonic()
    if first is None:
        first = now
        image.save(str(output.with_suffix('.png')))
    last = now
    report['frames'] += 1

def finished(path, ok):
    report['finished'].append({'path': path, 'success': ok})

preview.frame.connect(frame)
preview.error.connect(report['errors'].append)
preview.recording_finished.connect(finished)
preview.stopped.connect(app.quit)
preview.start(Camera.discover()[0]['path'], '720p · 30 fps', str(output), audio_source=args.audio, effects=EffectSettings(background='blur', blur=25))
QTimer.singleShot(args.seconds * 1000, preview.stop)
QTimer.singleShot((args.seconds + 20) * 1000, app.quit)
app.exec()
preview.shutdown()
report['wall_seconds'] = time.monotonic() - started
report['preview_fps'] = (report['frames'] - 1) / (last - first) if first and last and last > first else 0
report['diagnostics'] = preview.diagnostics
if output.exists():
    info = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(output)], text=True, capture_output=True, check=True)
    report['media'] = json.loads(info.stdout)
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-fps_mode', 'passthrough', '-enc_time_base:v', 'demux', '-f', 'null', '-'], check=True, timeout=30)
output.with_suffix('.json').write_text(json.dumps(report, indent=2))
print(json.dumps({k: v for k, v in report.items() if k != 'media'}, indent=2))
assert report['finished'] == [{'path': str(output), 'success': True}], report
assert not report['errors'], report['errors']
assert report['frames'] > 30, report
