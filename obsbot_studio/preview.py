"""Bounded MJPEG preview with an owned ffmpeg process."""
from pathlib import Path
from dataclasses import asdict
import json
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QImage

MODES = {
    "1080p · 30 fps": (1920, 1080, 30),
    "1080p · 60 fps": (1920, 1080, 60),
    "1080p · 120 fps": (1920, 1080, 120),
    "4K · 30 fps": (3840, 2160, 30),
    "720p · 30 fps": (1280, 720, 30),
    "720p · 60 fps": (1280, 720, 60),
    "720p · 120 fps": (1280, 720, 120),
}


class Preview(QObject):
    frame = Signal(QImage)
    error = Signal(str)
    stopped = Signal()
    started = Signal()
    recording_finished = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.started.connect(self.started)
        self.process.errorOccurred.connect(self._error)
        self.buffer = bytearray()
        self.diagnostics = ""
        self.stopping = False
        self.recording_path = None
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self.process.kill)

    @property
    def running(self):
        return self.process.state() != QProcess.NotRunning

    @staticmethod
    def arguments(path, mode, recording_path=None, slow_motion=False, audio_source=None):
        width, height, rate = MODES[mode]
        args = [
            "-hide_banner", "-loglevel", "warning", "-n",
            "-thread_queue_size", "16", "-f", "v4l2", "-timestamps", "abs", "-input_format", "mjpeg", "-framerate", str(rate),
            "-video_size", f"{width}x{height}", "-i", path,
        ]
        if recording_path:
            if audio_source and slow_motion:
                raise ValueError("Slow-motion recording is silent. Turn off the microphone.")
            if audio_source:
                args += ["-thread_queue_size", "64", "-isync", "0", "-f", "pulse", "-wallclock", "1", "-i", str(audio_source)]
            if slow_motion and rate <= 30:
                raise ValueError("Slow motion requires a 60 or 120 fps capture mode.")
            video_filter = f"setpts={rate / 30}*(PTS-STARTPTS),fps=30" if slow_motion else "null"
            args += [
                "-map", "0:v:0", "-vf", video_filter,
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "20",
                "-pix_fmt", "yuv420p",
            ]
            if audio_source:
                args += ["-map", "1:a:0", "-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-b:a", "192k"]
            else:
                args += ["-an"]
            args += ["-movflags", "+faststart", str(recording_path),
            ]
        return args + [
            "-map", "0:v:0", "-an", "-vf", "fps=30,scale=1280:-2", "-c:v", "mjpeg",
            "-q:v", "5", "-f", "image2pipe", "pipe:1",
        ]

    def start(self, path, mode, recording_path=None, slow_motion=False, audio_source=None, *, effects=None):
        if self.running:
            return
        if recording_path and Path(recording_path).exists():
            self.error.emit("Recording destination already exists. Choose a new file.")
            self.stopped.emit()
            return
        try:
            if effects is not None and effects.active:
                if slow_motion:
                    raise ValueError("Turn off effects to record slow motion.")
                if MODES[mode] != (1280, 720, 30):
                    raise ValueError("Effects require the 720p · 30 fps mode.")
                program = sys.executable
                args = ["-m", "obsbot_studio.effects_capture", "--device", path,
                        "--width", "1280", "--height", "720", "--settings", json.dumps(asdict(effects))]
                if recording_path:
                    args += ["--record", str(recording_path)]
                    if audio_source:
                        args += ["--audio", str(audio_source)]
            else:
                program = "ffmpeg"
                args = self.arguments(path, mode, recording_path, slow_motion, audio_source)
        except ValueError as exc:
            self.error.emit(str(exc))
            self.stopped.emit()
            return
        self.buffer.clear()
        self.diagnostics = ""
        self.stopping = False
        self.recording_path = str(recording_path) if recording_path else None
        self.process.start(program, args)

    def stop(self):
        if not self.running:
            self.stopped.emit()
            return
        self.stopping = True
        self.process.write(b"q\n")
        self.kill_timer.start(15000 if self.recording_path or self.process.program() == sys.executable else 3000)

    def shutdown(self):
        if self.running:
            self.stop()
            if not self.process.waitForFinished(15000):
                self.process.kill()
                self.process.waitForFinished(2000)

    def _stderr(self):
        self.diagnostics = (self.diagnostics + bytes(self.process.readAllStandardError()).decode("utf-8", "replace"))[-6000:]

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self.error.emit(f"Could not start {self.process.program()}. Check the app's capture dependencies.")
            self.recording_path = None
            self.stopped.emit()

    def _finished(self, code, status):
        self.kill_timer.stop()
        self._stderr()
        if self.recording_path:
            path = self.recording_path
            self.recording_path = None
            self.recording_finished.emit(path, code == 0 and Path(path).is_file())
        if not self.stopping or code != 0:
            self.error.emit(self.diagnostics.strip() or f"Preview ended (exit {code}).")
        self.buffer.clear()
        self.stopped.emit()

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        latest = None
        while True:
            start = self.buffer.find(b"\xff\xd8")
            if start < 0:
                self.buffer[:] = self.buffer[-1:]
                break
            end = self.buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start:
                    del self.buffer[:start]
                break
            latest = bytes(self.buffer[start:end + 2])
            del self.buffer[:end + 2]
        if len(self.buffer) > 16 * 1024 * 1024:
            self.buffer.clear()
            self.error.emit("Preview frame exceeded the memory limit.")
            self.stop()
        if latest:
            frame = QImage.fromData(latest, "JPEG")
            if not frame.isNull():
                self.frame.emit(frame)
