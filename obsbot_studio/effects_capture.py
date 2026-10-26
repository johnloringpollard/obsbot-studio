"""Capture once, composite once, and deliver the same frames to preview and MP4."""
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import av
import cv2

from .effects import EffectSettings, Processor


def capture_command(device, width, height, audio=''):
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
               '-thread_queue_size', '16', '-f', 'v4l2', '-input_format', 'mjpeg', '-framerate', '30',
               '-video_size', f'{width}x{height}', '-timestamps', 'abs', '-i', device]
    if audio:
        command += ['-thread_queue_size', '64', '-isync', '0', '-f', 'pulse', '-wallclock', '1', '-i', audio]
    command += ['-map', '0:v:0']
    if audio:
        command += ['-map', '1:a:0']
    command += ['-c:v', 'copy', '-fps_mode', 'passthrough']
    if audio:
        command += ['-af', 'aresample=async=1:first_pts=0:min_hard_comp=0.01', '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2']
    return command + ['-f', 'nut', 'pipe:1']


class Recorder:
    def __init__(self, path, width, height, audio):
        self.file = open(path, 'xb')
        self.container = None
        try:
            self.container = av.open(self.file, mode='w', format='mp4')
            self.video = self.container.add_stream('libx264', rate=30)
            self.video.width, self.video.height = width, height
            self.video.pix_fmt = 'yuv420p'
            self.video.time_base = Fraction(1, 1_000_000)
            self.video.codec_context.time_base = self.video.time_base
            self.video.options = {'preset': 'ultrafast', 'tune': 'zerolatency', 'crf': '20', 'bf': '0'}
            self.audio = self.container.add_stream('aac', rate=48000) if audio else None
            if self.audio:
                self.audio.layout = 'stereo'
                self.resampler = av.AudioResampler(format='fltp', layout='stereo', rate=48000)
            self.origin = None
        except BaseException:
            try:
                self.close()
            finally:
                Path(path).unlink(missing_ok=True)
            raise

    def write(self, frame, source_time):
        if self.origin is None:
            self.origin = source_time
        if isinstance(frame, av.VideoFrame):
            frame.time_base = self.video.time_base
            frame.pts = round((source_time - self.origin) / frame.time_base)
            for packet in self.video.encode(frame):
                self.container.mux(packet)
        elif self.audio:
            frame.pts = round((source_time - self.origin) * frame.sample_rate)
            frame.time_base = Fraction(1, frame.sample_rate)
            for converted in self.resampler.resample(frame):
                for packet in self.audio.encode(converted):
                    self.container.mux(packet)

    def close(self):
        if self.container is not None:
            try:
                if getattr(self, 'audio', None):
                    for frame in self.resampler.resample(None):
                        for packet in self.audio.encode(frame):
                            self.container.mux(packet)
                    for packet in self.audio.encode(None):
                        self.container.mux(packet)
                if getattr(self, 'video', None):
                    for packet in self.video.encode(None):
                        self.container.mux(packet)
            finally:
                self.container.close()
                self.container = None
                self.file.close()
        else:
            self.file.close()


def run(args):
    if not 2 <= args.width <= 1280 or not 2 <= args.height <= 720 or args.width % 2 or args.height % 2:
        raise ValueError('Effects require even dimensions up to 1280 × 720 at 30 fps')
    cv2.setNumThreads(4)
    processor = Processor(EffectSettings.from_dict(json.loads(args.settings)))
    capture = None
    source = None
    recorder = None
    stopped = threading.Event()
    completed = threading.Event()
    recording_created = False
    successful = False
    video_count = 0

    def stop(*unused):
        stopped.set()
        if capture is not None and capture.poll() is None:
            capture.send_signal(signal.SIGINT)

    def controls():
        for line in sys.stdin:
            if line.strip() == 'q':
                stop()
                return
        stop()

    def watchdog():
        stopped.wait()
        if not completed.wait(5) and capture is not None and capture.poll() is None:
            capture.kill()

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        if args.record and Path(args.record).exists():
            raise FileExistsError(f'Recording already exists: {args.record}')
        threading.Thread(target=controls, daemon=True).start()
        threading.Thread(target=watchdog, daemon=True).start()
        if args.input:
            source = av.open(args.input)
        else:
            # Linux kills FFmpeg too if the UI must forcibly terminate this helper.
            launcher = 'import ctypes,os,signal,sys; ctypes.CDLL(None).prctl(1,signal.SIGTERM); sys.exit(1) if os.getppid()==1 else os.execvp(sys.argv[1],sys.argv[1:])'
            capture = subprocess.Popen([sys.executable, '-c', launcher, *capture_command(args.device, args.width, args.height, args.audio)], stdout=subprocess.PIPE)
            if stopped.is_set():
                stop()
            source = av.open(capture.stdout, format='nut', options={'probesize': '32768', 'analyzeduration': '0'})
        videos = source.streams.video
        if not videos:
            raise ValueError('Input contains no video')
        if args.record:
            recorder = Recorder(args.record, args.width, args.height, bool(source.streams.audio))
            recording_created = True
        first_timestamp = None
        started = None
        lag_started = None
        pending_preview = b''
        os.set_blocking(sys.stdout.fileno(), False)
        for packet in source.demux():
            if args.input and stopped.is_set():
                break
            for frame in packet.decode():
                if frame.pts is None or frame.time_base is None:
                    raise ValueError('Capture frame has no timestamp')
                source_time = frame.pts * frame.time_base
                if isinstance(frame, av.VideoFrame):
                    video_count += 1
                    if not args.input:
                        now = time.monotonic()
                        if first_timestamp is None:
                            first_timestamp, started = source_time, now
                        lag = now - started - float(source_time - first_timestamp)
                        if lag > 3:
                            lag_started = lag_started or now
                            if now - lag_started > 2:
                                raise RuntimeError('Effects cannot keep up with capture; reduce resolution or disable effects')
                        else:
                            lag_started = None
                    bgr = frame.to_ndarray(format='bgr24')
                    if bgr.shape[:2] != (args.height, args.width):
                        bgr = cv2.resize(bgr, (args.width, args.height))
                    result = processor.process(bgr)
                    if recorder:
                        recorder.write(av.VideoFrame.from_ndarray(result, format='bgr24'), source_time)
                    ok, jpeg = cv2.imencode('.jpg', result, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if not ok:
                        raise ValueError('Cannot encode preview frame')
                    if not pending_preview:
                        pending_preview = jpeg.tobytes()
                    try:
                        written = os.write(sys.stdout.fileno(), pending_preview)
                        pending_preview = pending_preview[written:]
                    except BlockingIOError:
                        pass
                elif isinstance(frame, av.AudioFrame) and recorder:
                    recorder.write(frame, source_time)
        if not video_count:
            raise RuntimeError('Capture produced no video frames')
        if capture:
            code = capture.wait(timeout=5)
            if code and not (stopped.is_set() and code in (255, -signal.SIGINT)):
                raise RuntimeError(f'Camera capture failed with exit code {code}')
        successful = True
    finally:
        stop()
        try:
            if source:
                source.close()
            if capture:
                try:
                    capture.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    capture.kill()
                    capture.wait()
                capture.stdout.close()
            if recorder:
                recorder.close()
        except BaseException:
            successful = False
            raise
        finally:
            completed.set()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if recording_created and not successful and not video_count:
                Path(args.record).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='/dev/video0')
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--record')
    parser.add_argument('--audio', default='')
    parser.add_argument('--input')
    args = parser.parse_args()
    try:
        run(args)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Effects capture: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
