"""One-shot, conservative exposure compensation with durable, camera-scoped Undo."""
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile
import time

import cv2
import numpy as np

CONTROL = 'backlight_compensation'


@dataclass(frozen=True)
class Metrics:
    median: float
    clipped: float
    dark: float
    face: tuple

    @property
    def score(self):
        return max(0, 45 - self.median) / 45 + self.clipped * 4


@dataclass(frozen=True)
class Result:
    message: str
    changed: bool = False
    before: Metrics | None = None
    after: Metrics | None = None


def detector():
    paths = [Path(f'/usr/share/opencv{v}/haarcascades/haarcascade_frontalface_default.xml') for v in ('5', '4', '')]
    if hasattr(cv2, 'data'):
        paths.append(Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml')
    path = next((p for p in paths if p.is_file()), None)
    if path is None:
        raise RuntimeError('Face detector unavailable. Install the system OpenCV cascade data.')
    cascade = cv2.CascadeClassifier(str(path))
    if cascade.empty():
        raise RuntimeError('Face detector could not be loaded.')
    return lambda frame: cascade.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(80, 80))


def measure(frame, face):
    x, y, w, h = map(int, face)
    # Sample inside the face box to reduce hair and background influence.
    roi = frame[y + h // 5:y + 4 * h // 5, x + w // 5:x + 4 * w // 5]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return Metrics(float(np.median(gray)), float(np.mean(np.max(roi, axis=2) >= 250)), float(np.mean(gray <= 20)), (x, y, w, h))


def same_face(a, b):
    x, y, w, h = a
    xx, yy, ww, hh = b
    intersection = max(0, min(x+w, xx+ww)-max(x, xx)) * max(0, min(y+h, yy+hh)-max(y, yy))
    return intersection / max(1, w*h + ww*hh - intersection) >= .7


def measure_burst(frames, detect, reference=None):
    samples = []
    for frame in frames:
        faces = detect(frame)
        if len(faces) != 1:
            raise RuntimeError('Keep exactly one clearly visible face in view. Settings left unchanged.')
        metric = measure(frame, faces[0])
        if (reference is not None and not same_face(reference.face, metric.face)) or (samples and not same_face(samples[0].face, metric.face)):
            raise RuntimeError('Face moved during analysis. Hold still and try again.')
        samples.append(metric)
    if len(samples) < 3 or max(m.median for m in samples)-min(m.median for m in samples) > 10 or max(m.clipped for m in samples)-min(m.clipped for m in samples) > .03:
        raise RuntimeError('Lighting has not settled. Settings left unchanged; try again.')
    return Metrics(float(np.median([m.median for m in samples])), float(np.median([m.clipped for m in samples])), float(np.median([m.dark for m in samples])), samples[-1].face)


def capture(camera, timeout):
    # Skip two seconds while the sensor settles, then retain three spaced frames.
    with tempfile.TemporaryDirectory(prefix='obsbot-exposure-') as directory:
        target = str(Path(directory) / 'burst.mjpeg')
        command = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'v4l2', '-input_format', 'mjpeg', '-video_size', '1280x720', '-framerate', '30', '-i', camera.path, '-vf', "select='gte(n,60)*not(mod(n,6))'", '-frames:v', '3', '-fps_mode', 'vfr', '-c:v', 'mjpeg', '-q:v', '3', '-fs', '8000000', '-f', 'mjpeg', target]
        with tempfile.TemporaryFile() as errors:
            process = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=errors, timeout=min(6, timeout))
            if process.returncode:
                raise RuntimeError('Could not capture raw camera frames. Close other camera applications.')
        data = Path(target).read_bytes()
    frames = []
    start = 0
    while (start := data.find(b'\xff\xd8', start)) >= 0:
        end = data.find(b'\xff\xd9', start)
        if end < 0:
            break
        frame = cv2.imdecode(np.frombuffer(data[start:end+2], np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            frames.append(frame)
        start = end + 2
    return frames


def undo_path(camera):
    return camera.state_dir / f'{camera.key}-exposure-undo.json'


def undo_available(camera):
    return undo_path(camera).is_file()


def _value(snapshot, key):
    return next(c['value'] for c in snapshot['controls'] if c['id'] == key)


def _restore(camera, value):
    state = camera.apply(CONTROL, value)
    if _value(state, CONTROL) != value:
        raise RuntimeError('Exposure restore could not be confirmed. Undo remains available.')


def undo(camera):
    path = undo_path(camera)
    data = json.loads(path.read_text())
    if data.get('device') != camera.path or data.get('key') != camera.key or set(data.get('controls', {})) != {CONTROL} or type(data['controls'][CONTROL]) is not int:
        raise RuntimeError('Undo record does not match this camera.')
    _restore(camera, data['controls'][CONTROL])
    path.unlink()
    return Result('Original exposure compensation restored and confirmed.')


def _restore_undo_record(camera, previous):
    path = undo_path(camera)
    if previous is None:
        path.unlink()
    else:
        temp = path.with_suffix('.tmp')
        temp.write_bytes(previous)
        temp.chmod(0o600)
        temp.replace(path)


def run(camera, *, capture_frames=capture, detect=None, progress=lambda message: None):
    deadline = time.monotonic() + 30
    state = camera.snapshot()
    controls = {c['id']: c for c in state['controls']}
    if state.get('status', {}).get('sleeping'):
        return Result('Wake the camera before tuning. Settings left unchanged.')
    if controls.get('auto_exposure', {}).get('value') not in (0, 2, 3):
        return Result('Enable auto exposure before tuning. Settings left unchanged.')
    control = controls.get(CONTROL)
    if not control or not control['enabled']:
        return Result('Exposure compensation is unavailable. Settings left unchanged.')
    original = control['value']
    touched = False
    before = None
    previous_undo = None
    try:
        detect = detect or detector()
        progress('Measuring face exposure. Hold still…')
        before = measure_burst(capture_frames(camera, max(.1, deadline-time.monotonic())), detect)
        direction = -1 if before.clipped > .08 else 1 if before.median < 40 and before.dark > .2 else 0
        if not direction:
            return Result('Face exposure is within the acceptance range. Settings left unchanged.', before=before)
        trial = original + direction * max(1, control.get('step', 1))
        allowed = [o['value'] for o in control.get('options', [])]
        if not control['min'] <= trial <= control['max'] or (allowed and trial not in allowed):
            return Result('Exposure compensation is at its limit. Settings left unchanged.', before=before)
        if deadline-time.monotonic() < 20:
            return Result('Analysis took too long. Settings left unchanged.', before=before)
        path = undo_path(camera)
        previous_undo = path.read_bytes() if path.exists() else None
        camera._write_json(path, {'version': 1, 'device': camera.path, 'key': camera.key, 'controls': {CONTROL: original}})
        touched = True
        progress('Testing one exposure step. Hold still…')
        applied = camera.apply(CONTROL, trial)
        if _value(applied, CONTROL) != trial:
            raise RuntimeError('Exposure change could not be confirmed.')
        if deadline-time.monotonic() < 6:
            raise RuntimeError('Analysis time limit reached.')
        after = measure_burst(capture_frames(camera, min(6, deadline-time.monotonic())), detect, before)
        improvement = after.score < before.score - .04
        safe = after.clipped <= before.clipped + .005 and after.dark <= before.dark + .02
        if improvement and safe and time.monotonic() < deadline:
            return Result(f'Exposure tuned {original} → {trial}. Face brightness {before.median:.0f} → {after.median:.0f}/255; clipped highlights {before.clipped:.0%} → {after.clipped:.0%}. Undo is available.', True, before, after)
        _restore(camera, original)
        _restore_undo_record(camera, previous_undo)
        touched = False
        return Result('No clear improvement. Original exposure restored and confirmed.', before=before, after=after)
    except Exception as exc:
        if touched:
            try:
                _restore(camera, original)
                _restore_undo_record(camera, previous_undo)
            except Exception as restore_error:
                return Result(f'Tuning stopped: {exc} Restore failed: {restore_error} Undo remains available.', before=before)
            return Result(f'Tuning stopped: {exc} Original exposure restored and confirmed.', before=before)
        return Result(f'Settings left unchanged. {exc}', before=before)
