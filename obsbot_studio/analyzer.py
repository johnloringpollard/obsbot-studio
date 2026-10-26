"""Measured portrait exposure tuning with durable, camera-scoped Undo."""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
from pathlib import Path
import subprocess
import tempfile
import time

import cv2
import numpy as np

CONTROL = 'backlight_compensation'
ALLOWED_CONTROLS = {CONTROL, 'brightness'}


@dataclass(frozen=True)
class TuneOptions:
    target: int = 155

    def __post_init__(self):
        if type(self.target) is not int or not 100 <= self.target <= 180:
            raise ValueError('Face brightness target must be an integer from 100 to 180.')


@dataclass(frozen=True)
class Metrics:
    median: float
    clipped: float
    dark: float
    face: tuple


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
    # Skip three seconds while the sensor settles, then retain three spaced frames.
    with tempfile.TemporaryDirectory(prefix='obsbot-exposure-') as directory:
        target = str(Path(directory) / 'burst.mjpeg')
        command = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'v4l2', '-input_format', 'mjpeg', '-video_size', '1280x720', '-framerate', '30', '-i', camera.path, '-vf', "select='gte(n,90)*not(mod(n,6))'", '-frames:v', '3', '-fps_mode', 'vfr', '-c:v', 'mjpeg', '-q:v', '3', '-fs', '8000000', '-f', 'mjpeg', target]
        with tempfile.TemporaryFile() as errors:
            process = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=errors, timeout=min(8, timeout))
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


@contextmanager
def tuning_lock(camera):
    camera.state_dir.mkdir(parents=True, exist_ok=True)
    with (camera.state_dir / f'{camera.key}-tuning.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another tuning or Undo operation is running for this camera.') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _restore(camera, values):
    errors = []
    for key, value in values.items():
        try:
            if _value(camera.apply(key, value), key) != value:
                raise RuntimeError(f'{key} restore could not be confirmed.')
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError('; '.join(errors))


def undo(camera):
    with tuning_lock(camera):
        path = undo_path(camera)
        data = json.loads(path.read_text())
        values = data.get('controls', {})
        version = data.get('version')
        valid = isinstance(values, dict) and bool(values) and set(values) <= ALLOWED_CONTROLS and all(type(v) is int for v in values.values())
        if data.get('device') != camera.path or data.get('key') != camera.key or version not in (1, 2) or not valid or (version == 1 and set(values) != {CONTROL}):
            raise RuntimeError('Undo record does not match this camera.')
        _restore(camera, values)
        path.unlink()
        return Result('Previous tuning settings restored and confirmed.')


def _restore_undo_record(camera, previous):
    path = undo_path(camera)
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        temp = path.with_suffix('.tmp')
        temp.write_bytes(previous)
        temp.chmod(0o600)
        temp.replace(path)


def run(camera, *, options=TuneOptions(), capture_frames=capture, detect=None, progress=lambda message: None):
    try:
        with tuning_lock(camera):
            return _run(camera, options, capture_frames, detect, progress)
    except Exception as exc:
        return Result(f'Settings left unchanged. {exc}')


def _run(camera, options, capture_frames, detect, progress):
    deadline = time.monotonic() + 60
    state = camera.snapshot()
    controls = {c['id']: c for c in state['controls']}
    if state.get('status', {}).get('sleeping'):
        return Result('Wake the camera before tuning. Settings left unchanged.')
    if controls.get('auto_exposure', {}).get('value') not in (0, 2, 3):
        return Result('Enable auto exposure before tuning. Settings left unchanged.')
    if not controls.get(CONTROL, {}).get('enabled'):
        return Result('Exposure compensation is unavailable. Settings left unchanged.')
    original = {key: c['value'] for key, c in controls.items() if key in ALLOWED_CONTROLS}
    best_values = original.copy()
    touched = {}
    before = best = None
    previous_undo = None

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds < 8:
            raise RuntimeError('Analysis time limit reached.')
        return min(8, seconds)

    try:
        detect = detect or detector()
        progress('Measuring face brightness. Hold still…')
        before = best = measure_burst(capture_frames(camera, remaining()), detect)
        if abs(before.median - options.target) <= 7 and before.clipped <= .02:
            return Result(f'Face brightness {before.median:.0f}/255 is within 7 of target {options.target}; clipped highlights {before.clipped:.1%}. Settings left unchanged.', before=before, after=before)
        path = undo_path(camera)
        previous_undo = path.read_bytes() if path.exists() else None
        key = CONTROL
        for attempt in range(6):
            recovering = best.clipped > .02
            if not recovering and abs(best.median - options.target) <= 7:
                break
            direction = -1 if recovering or best.median > options.target else 1
            control = controls.get(key)
            if not control or not control.get('enabled'):
                break
            step, budget = (1, 3) if key == CONTROL else (2, 6)
            trial = best_values[key] + direction * step
            allowed = [o['value'] for o in control.get('options', [])]
            valid = control['min'] <= trial <= control['max'] and abs(trial-original[key]) <= budget and (not allowed or trial in allowed) and (trial-control['min']) % max(1, control.get('step', 1)) == 0
            if not valid:
                if key == CONTROL:
                    key = 'brightness'
                    continue
                break
            remaining()
            recovery = {**touched, key: original[key]}
            camera._write_json(path, {'version': 2, 'device': camera.path, 'key': camera.key, 'controls': recovery})
            touched = recovery
            progress(f'Trial {attempt + 1}/6: measuring face brightness toward {options.target}. Hold still…')
            applied = camera.apply(key, trial)
            if _value(applied, key) != trial:
                raise RuntimeError(f'{key} change could not be confirmed.')
            after = measure_burst(capture_frames(camera, remaining()), detect, before)
            if time.monotonic() >= deadline:
                raise RuntimeError('Analysis time limit reached.')
            safe = after.clipped <= max(best.clipped, .02) + .002 and after.dark <= before.dark + .02
            highlight_gain = recovering and (after.clipped <= best.clipped - .005 or after.clipped <= .02)
            gain = abs(best.median-options.target) - abs(after.median-options.target) >= 2
            accepted = safe and (highlight_gain if recovering else gain)
            overshot = (best.median-options.target) * (after.median-options.target) < 0
            if accepted:
                best, best_values[key] = after, trial
                if overshot and not highlight_gain:
                    break
            else:
                _restore(camera, {key: best_values[key]})
                if not safe or (recovering and not highlight_gain) or overshot:
                    break
                if key == CONTROL:
                    key = 'brightness'
                else:
                    break
        changed = any(best_values[k] != original[k] for k in touched)
        if not changed:
            _restore_undo_record(camera, previous_undo)
        changes = ', '.join(f'{k.replace("_", " ")} {original[k]} → {best_values[k]}' for k in touched if original[k] != best_values[k])
        summary = f'Face brightness {before.median:.0f} → {best.median:.0f}/255, target {options.target}; clipped highlights {before.clipped:.1%} → {best.clipped:.1%}.'
        return Result(f'{summary} {changes}. Undo is available.' if changed else f'{summary} No clear improvement; original settings confirmed.', changed, before, best)
    except Exception as exc:
        if touched:
            try:
                # Recovery may exceed the cooperative analysis deadline.
                _restore(camera, touched)
                _restore_undo_record(camera, previous_undo)
            except Exception as restore_error:
                return Result(f'Tuning stopped: {exc} Restore failed: {restore_error} Undo remains available.', before=before)
            return Result(f'Tuning stopped: {exc} Original tuning settings restored and confirmed.', before=before)
        return Result(f'Settings left unchanged. {exc}', before=before)
