import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import av
import numpy as np
from obsbot_studio.effects_capture import Recorder, capture_command


class CaptureTest(unittest.TestCase):
    def test_command_sync(self):
        command = capture_command('/dev/fake', 1280, 720, 'fake-mic')
        self.assertIn('-isync', command)
        self.assertEqual(command[command.index('-timestamps') + 1], 'abs')
        self.assertIn('passthrough', command)

    def test_real_pipeline_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'input.nut'
            output = Path(root) / 'output.mp4'
            preview = Path(root) / 'preview.mjpg'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=30', '-f', 'lavfi', '-i', 'sine=sample_rate=48000', '-t', '1.5', '-c:v', 'rawvideo', '-pix_fmt', 'bgr24', '-threads:v', '1', '-c:a', 'pcm_s16le', str(source)], check=True)
            command = [sys.executable, '-m', 'obsbot_studio.effects_capture', '--input', str(source), '--width', '160', '--height', '120', '--settings', json.dumps({'filter': 'mono'}), '--record', str(output)]
            with open(preview, 'wb') as pipe:
                proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=pipe, stderr=subprocess.PIPE)
                self.assertEqual(proc.wait(timeout=30), 0, proc.stderr.read().decode())
                proc.stdin.close()
                proc.stderr.close()
            with av.open(str(output)) as container:
                self.assertEqual(len(container.streams.audio), 1)
                frames = list(container.decode(video=0))
                self.assertEqual(len(frames), 45)
                bgr = frames[10].to_ndarray(format='bgr24')
                self.assertLess(np.abs(bgr[:, :, 0].astype(int) - bgr[:, :, 2]).mean(), 2)
            with av.open(str(output)) as container:
                audio = list(container.decode(audio=0))
                audio_end = float(audio[-1].pts * audio[-1].time_base) + audio[-1].samples / audio[-1].sample_rate
                self.assertLess(abs(audio_end - 1.5), .05)
            self.assertEqual(preview.read_bytes().count(b'\xff\xd8'), 45)
            stopped_output = Path(root) / 'stopped.mp4'
            stopped_command = command[:-1] + [str(stopped_output)]
            stopped = subprocess.Popen(stopped_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertTrue(stopped.stdout.read(1024))
            stopped.stdin.write(b'q\n')
            stopped.stdin.flush()
            self.assertEqual(stopped.wait(timeout=10), 0, stopped.stderr.read().decode())
            stopped.stdin.close()
            stopped.stdout.close()
            stopped.stderr.close()
            with av.open(str(stopped_output)) as container:
                self.assertGreater(len(list(container.decode(video=0))), 0)
            before = output.read_bytes()
            proc = subprocess.run(command, input=b'', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(output.read_bytes(), before)

    def test_audio_and_video_offsets(self):
        from fractions import Fraction
        for audio_offset, video_offset in [(Fraction(2, 5), Fraction(0)), (Fraction(0), Fraction(2, 5))]:
            with self.subTest(audio_offset=audio_offset), tempfile.TemporaryDirectory() as root:
                output = Path(root) / 'offset.mp4'
                recorder = Recorder(output, 160, 120, True)
                events = [(Fraction(i, 30) + video_offset, 'video') for i in range(30)]
                events += [(Fraction(i, 30) + audio_offset, 'audio') for i in range(30)]
                for timestamp, kind in sorted(events):
                    if kind == 'video':
                        frame = av.VideoFrame.from_ndarray(np.zeros((120, 160, 3), np.uint8), format='bgr24')
                    else:
                        frame = av.AudioFrame.from_ndarray(np.zeros((1, 3200), np.int16), format='s16', layout='stereo')
                        frame.sample_rate = 48000
                    recorder.write(frame, timestamp + 1000)
                recorder.close()
                with av.open(str(output)) as container:
                    video = container.streams.video[0]
                    audio = container.streams.audio[0]
                    offset = float(audio.start_time * audio.time_base - video.start_time * video.time_base)
                    self.assertLess(abs(offset - float(audio_offset - video_offset)), .025)

    def test_pts_survive_slow_processing_and_dropped_frames(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'slow.mp4'
            recorder = Recorder(output, 160, 120, True)
            from fractions import Fraction
            for index in range(30):
                source_time = Fraction(index, 30)
                if index % 3 == 0:
                    time.sleep(.04)
                    recorder.write(av.VideoFrame.from_ndarray(np.zeros((120, 160, 3), np.uint8), format='bgr24'), source_time)
                audio = av.AudioFrame.from_ndarray(np.zeros((1, 3200), np.int16), format='s16', layout='stereo')
                audio.sample_rate = 48000
                recorder.write(audio, source_time)
            recorder.close()
            with av.open(str(output)) as container:
                video = list(container.decode(video=0))
                self.assertEqual(len(video), 10)
                self.assertAlmostEqual(float(video[-1].pts * video[-1].time_base), .9, places=3)
            with av.open(str(output)) as container:
                audio = list(container.decode(audio=0))
                self.assertLess(abs(float(audio[-1].pts * audio[-1].time_base) + audio[-1].samples / 48000 - 1), .03)

if __name__ == '__main__':
    unittest.main()
