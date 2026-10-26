"""Hardware-free regression checks for capture recovery and Pulse timestamp overlap."""
from fractions import Fraction
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import av
import numpy as np

from obsbot_studio.effects_capture import capture_command


def generate_video(path):
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=160x120:rate=30', '-t', '1', '-c:v', 'ffv1', str(path)],
                   check=True, timeout=20, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_helper(source, output, script=None):
    command = [sys.executable]
    command += ['-c', script] if script else ['-m', 'obsbot_studio.effects_capture']
    command += ['--input', str(source), '--width', '160', '--height', '120',
                '--settings', '{}', '--record', str(output)]
    with tempfile.TemporaryFile() as preview:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=preview, stderr=subprocess.PIPE)
        try:
            status = process.wait(timeout=30)
            error = process.stderr.read().decode()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdin.close()
            process.stderr.close()
    return status, error


class CaptureRecoveryTest(unittest.TestCase):
    def test_processing_failure_preserves_completed_frames(self):
        script = '''
import sys
from obsbot_studio import effects_capture
class FailingProcessor:
    def __init__(self, settings):
        self.count = 0
    def process(self, frame):
        self.count += 1
        if self.count == 13:
            raise RuntimeError('injected frame 13 failure')
        return frame
effects_capture.Processor = FailingProcessor
sys.exit(effects_capture.main())
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            output = Path(directory) / 'recoverable.mp4'
            generate_video(source)
            status, error = run_helper(source, output, script)
            self.assertNotEqual(status, 0)
            self.assertIn('injected frame 13 failure', error)
            self.assertTrue(output.is_file())
            with av.open(str(output)) as container:
                frames = list(container.decode(video=0))
            self.assertEqual(len(frames), 12)
            self.assertAlmostEqual(float(frames[-1].pts * frames[-1].time_base), 11 / 30, delta=.001)

    def test_capture_filter_repairs_overlapping_pcm_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'overlap.nut'
            normalized = Path(directory) / 'normalized.nut'
            output = Path(directory) / 'result.mp4'
            starts = [4747, 5114, 6113, 7663, 9669, 11989]
            starts += list(range(14389, 60000, 2400))
            with av.open(str(source), 'w', format='nut') as container:
                video = container.add_stream('ffv1', rate=30)
                video.width, video.height = 160, 120
                video.pix_fmt = 'yuv420p'
                audio = container.add_stream('pcm_s16le', rate=48000)
                audio.layout = 'stereo'
                events = [(Fraction(index, 30), 'video', index) for index in range(42)]
                events += [(Fraction(start, 48000), 'audio', start) for start in starts]
                for timestamp, kind, index in sorted(events):
                    if kind == 'video':
                        frame = av.VideoFrame.from_ndarray(np.zeros((120, 160, 3), np.uint8), format='bgr24')
                        frame.pts = index
                        frame.time_base = Fraction(1, 30)
                        stream = video
                    else:
                        tone = (np.sin(np.arange(2400) * 2 * np.pi * 440 / 48000) * 10000).astype(np.int16)
                        stereo = np.repeat(tone, 2)[None, :]
                        frame = av.AudioFrame.from_ndarray(stereo, format='s16', layout='stereo')
                        frame.sample_rate = 48000
                        frame.pts = index
                        frame.time_base = Fraction(1, 48000)
                        stream = audio
                    for packet in stream.encode(frame):
                        container.mux(packet)
                for stream in (video, audio):
                    for packet in stream.encode(None):
                        container.mux(packet)
            broken_status, broken_error = run_helper(source, Path(directory) / 'unfiltered.mp4')
            self.assertNotEqual(broken_status, 0, 'Fixture must reproduce the unfiltered AAC mux failure')
            self.assertIn('Invalid argument', broken_error)
            command = capture_command('/dev/fake', 160, 120, 'fake-mic')
            audio_filter = command[command.index('-af') + 1]
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-map', '0:v:0',
                            '-map', '0:a:0', '-c:v', 'copy', '-af', audio_filter,
                            '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', str(normalized)],
                           check=True, timeout=20, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with av.open(str(normalized)) as container:
                audio_frames = list(container.decode(audio=0))
            for before, after in zip(audio_frames, audio_frames[1:]):
                self.assertGreaterEqual(after.pts * after.time_base,
                                        before.pts * before.time_base + Fraction(before.samples, before.sample_rate))
            status, error = run_helper(normalized, output)
            self.assertEqual(status, 0, error)
            with av.open(str(output)) as container:
                self.assertEqual(len(list(container.decode(video=0))), 42)
            with av.open(str(output)) as container:
                audio_frames = list(container.decode(audio=0))
            samples = np.concatenate([frame.to_ndarray()[0] for frame in audio_frames])
            onset = np.flatnonzero(np.abs(samples) > .02)[0] / 48000
            self.assertAlmostEqual(onset, starts[0] / 48000, delta=.015)
            end = float(audio_frames[-1].pts * audio_frames[-1].time_base) + audio_frames[-1].samples / 48000
            with av.open(str(normalized)) as container:
                normalized_audio = list(container.decode(audio=0))
            last = normalized_audio[-1]
            normalized_end = float(last.pts * last.time_base) + last.samples / last.sample_rate
            self.assertAlmostEqual(end, normalized_end, delta=.025)
            self.assertAlmostEqual(end, (starts[-1] + 2400) / 48000, delta=.025)
            self.assertGreater(end, 1.25)
            self.assertLess(end, 1.45)


if __name__ == '__main__':
    unittest.main()
