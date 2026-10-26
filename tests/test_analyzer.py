"""Offline behavioral checks; no video devices are opened."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import cv2

import numpy as np
from obsbot_studio import analyzer as a


class Camera:
    def __init__(self, directory):
        self.state_dir = Path(directory)
        self.path = '/dev/test-camera'
        self.key = 'test'
        self.value = 9
        self.writes = []
        self.fail_write = False
        self.fail_restore = False
        self.mode = 0

    def snapshot(self):
        return {'controls': [{'id': 'auto_exposure', 'value': self.mode}, {'id': a.CONTROL, 'value': self.value, 'min': 0, 'max': 18, 'step': 1, 'enabled': True}], 'device': {'path': self.path}}

    def apply(self, key, value):
        assert key == a.CONTROL
        self.writes.append(value)
        self.value = value
        if self.fail_write and value != 9 or self.fail_restore and value == 9:
            raise RuntimeError('write failed')
        return self.snapshot()

    @staticmethod
    def _write_json(path, data):
        path.write_text(json.dumps(data))


def burst(value):
    return [np.full((200, 200, 3), value, np.uint8) for _ in range(3)]


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.camera = Camera(self.tmp.name)
        self.detect = lambda frame: [(30, 30, 120, 120)]

    def run_tune(self, before=137, after=155, **kwargs):
        return a.run(self.camera, capture_frames=lambda camera, timeout: burst(before if camera.value == 9 else after), detect=self.detect, **kwargs)

    def test_capture_requests_settled_bounded_raw_burst(self):
        def ffmpeg(command, **kwargs):
            self.assertIn('1280x720', command)
            self.assertIn("select='gte(n,90)*not(mod(n,6))'", command)
            self.assertEqual(kwargs['timeout'], 8)
            self.assertEqual(command[command.index('-fs')+1], '8000000')
            encoded = cv2.imencode('.jpg', burst(100)[0])[1].tobytes()
            Path(command[-1]).write_bytes(encoded * 3)
            return SimpleNamespace(returncode=0)
        with patch.object(a.subprocess, 'run', side_effect=ffmpeg):
            frames = a.capture(self.camera, 10)
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0].shape, (200, 200, 3))

    def test_single_channel_clipping_is_measured_and_corrected(self):
        clipped = np.full((200, 200, 3), (80, 80, 255), np.uint8)
        corrected = np.full((200, 200, 3), (70, 70, 230), np.uint8)
        metric = a.measure(clipped, (30, 30, 120, 120))
        self.assertLess(metric.median, 245)
        self.assertEqual(metric.clipped, 1)
        result = a.run(self.camera, capture_frames=lambda camera, timeout: [clipped if camera.value == 9 else corrected] * 3, detect=self.detect)
        self.assertTrue(result.changed)
        self.assertEqual(self.camera.value, 8)

    def test_repeat_tuning_replaces_undo_with_latest_start(self):
        self.assertTrue(self.run_tune().changed)
        result = a.run(self.camera, capture_frames=lambda camera, timeout: burst(137 if camera.value == 10 else 155), detect=self.detect)
        self.assertTrue(result.changed)
        self.assertEqual(self.camera.writes, [10, 11])
        self.assertEqual(json.loads(a.undo_path(self.camera).read_text())['controls'], {a.CONTROL: 10})
        a.undo(self.camera)
        self.assertEqual(self.camera.value, 10)

    def test_prior_undo_survives_unchanged_and_rolled_back_runs(self):
        self.assertTrue(self.run_tune().changed)
        previous = a.undo_path(self.camera).read_bytes()
        for capture, detect in (
            (lambda *args: burst(155), self.detect),
            (lambda *args: burst(15), lambda frame: []),
            (lambda *args: burst(15), self.detect),
        ):
            self.assertFalse(a.run(self.camera, capture_frames=capture, detect=detect).changed)
            self.assertEqual(a.undo_path(self.camera).read_bytes(), previous)
            self.assertEqual(self.camera.value, 10)
        def failing_capture(camera, timeout):
            if camera.value != 10:
                raise RuntimeError('capture failed')
            return burst(15)
        self.assertFalse(a.run(self.camera, capture_frames=failing_capture, detect=self.detect).changed)
        self.assertEqual(a.undo_path(self.camera).read_bytes(), previous)
        self.assertEqual(self.camera.value, 10)

    def test_failed_repeat_rollback_keeps_latest_recovery_undo(self):
        self.assertTrue(self.run_tune().changed)
        apply = self.camera.apply
        def fail_restore(key, value):
            if value == 10:
                raise RuntimeError('restore failed')
            return apply(key, value)
        self.camera.apply = fail_restore
        result = a.run(self.camera, capture_frames=lambda *args: burst(15), detect=self.detect)
        self.assertIn('Undo remains available', result.message)
        self.assertEqual(json.loads(a.undo_path(self.camera).read_text())['controls'], {a.CONTROL: 10})

    def test_good_image_and_manual_mode_do_not_write(self):
        self.assertFalse(self.run_tune(155).changed)
        self.camera.mode = 1
        self.assertIn('Enable auto exposure', self.run_tune().message)
        self.assertEqual(self.camera.writes, [])

    def test_missing_multiple_or_unstable_face_do_not_write(self):
        for faces in ([], [(0, 0, 80, 80), (90, 90, 80, 80)]):
            self.detect = lambda frame: faces
            self.assertFalse(self.run_tune().changed)
        self.detect = lambda frame: [(30, 30, 120, 120)]
        a.run(self.camera, capture_frames=lambda *args: [burst(v)[0] for v in (15, 100, 15)], detect=self.detect)
        self.assertEqual(self.camera.writes, [])

    def test_improvement_and_scoped_undo(self):
        result = self.run_tune()
        self.assertTrue(result.changed)
        self.assertEqual(self.camera.writes, [10])
        data = json.loads(a.undo_path(self.camera).read_text())
        self.assertEqual(data['controls'], {a.CONTROL: 9})
        self.camera.path = '/dev/other-camera'
        with self.assertRaises(RuntimeError):
            a.undo(self.camera)
        self.assertEqual(self.camera.writes, [10])
        self.camera.path = '/dev/test-camera'
        a.undo(self.camera)
        self.assertEqual(self.camera.writes, [10, 9])
        self.assertFalse(a.undo_available(self.camera))

    def test_no_improvement_restores(self):
        self.assertFalse(self.run_tune(before=15, after=15).changed)
        self.assertEqual(self.camera.writes, [10, 9])
        self.assertFalse(a.undo_available(self.camera))

    def test_write_or_capture_failure_restores(self):
        self.camera.fail_write = True
        self.assertFalse(self.run_tune().changed)
        self.assertEqual(self.camera.writes, [10, 9])
        self.camera.fail_write = False
        self.camera.writes.clear()
        def capture(camera, timeout):
            if camera.value != 9:
                raise RuntimeError('capture failed')
            return burst(15)
        a.run(self.camera, capture_frames=capture, detect=self.detect)
        self.assertEqual(self.camera.writes, [10, 9])

    def test_failed_restore_retains_undo(self):
        self.camera.fail_restore = True
        result = self.run_tune(before=15, after=15)
        self.assertIn('Undo remains available', result.message)
        self.assertTrue(a.undo_available(self.camera))

    def test_clipping_regression_and_face_movement_restore(self):
        self.assertFalse(self.run_tune(after=250).changed)
        self.assertEqual(self.camera.writes, [10, 9])
        self.camera.writes.clear()
        self.detect = lambda frame: [(30, 30, 120, 120)] if self.camera.value == 9 else [(80, 80, 120, 120)]
        self.assertFalse(self.run_tune().changed)
        self.assertEqual(self.camera.writes, [10, 9])


class PortraitTests(AnalyzerTests):
    def setUp(self):
        super().setUp()
        self.camera.brightness = 47
        base_snapshot = self.camera.snapshot
        base_apply = self.camera.apply
        def snapshot():
            state = base_snapshot()
            state['controls'].append({'id': 'brightness', 'value': self.camera.brightness, 'min': 0, 'max': 100, 'step': 1, 'enabled': True})
            return state
        def apply(key, value):
            if key == 'brightness':
                self.camera.brightness = value
                return snapshot()
            return base_apply(key, value)
        self.camera.snapshot = snapshot
        self.camera.apply = apply

    def test_iterative_target_and_noop(self):
        result = a.run(self.camera, capture_frames=lambda camera, timeout: burst(137 + 6*(camera.value-9)), detect=self.detect)
        self.assertTrue(result.changed)
        self.assertEqual(result.after.median, 149)
        self.assertEqual(self.camera.value, 11)
        self.camera.writes.clear()
        self.assertFalse(self.run_tune(155).changed)
        self.assertEqual(self.camera.writes, [])

    def test_plateau_uses_brightness_and_undo_restores_both(self):
        result = a.run(self.camera, capture_frames=lambda camera, timeout: burst(137 + 4*(camera.brightness-47)), detect=self.detect)
        self.assertTrue(result.changed)
        self.assertEqual(result.after.median, 153)
        self.assertEqual(self.camera.value, 9)
        self.assertEqual(self.camera.brightness, 51)
        a.undo(self.camera)
        self.assertEqual((self.camera.value, self.camera.brightness), (9, 47))

    def test_late_failure_restores_all_modified_controls(self):
        def capture(camera, timeout):
            if camera.brightness > 47:
                raise RuntimeError('late capture failure')
            return burst(120 + min(camera.value-9, 1)*5)
        result = a.run(self.camera, capture_frames=capture, detect=self.detect)
        self.assertFalse(result.changed)
        self.assertIn('restored and confirmed', result.message)
        self.assertEqual((self.camera.value, self.camera.brightness), (9, 47))
        self.assertFalse(a.undo_available(self.camera))

    def test_old_record_undo_and_disallowed_record(self):
        path = a.undo_path(self.camera)
        self.camera._write_json(path, {'version': 1, 'device': self.camera.path, 'key': self.camera.key, 'controls': {a.CONTROL: 7}})
        a.undo(self.camera)
        self.assertEqual(self.camera.value, 7)
        self.camera._write_json(path, {'version': 2, 'device': self.camera.path, 'key': self.camera.key, 'controls': {'contrast': 7}})
        with self.assertRaises(RuntimeError):
            a.undo(self.camera)

    def test_concurrent_tuning_and_undo_do_not_write(self):
        with a.tuning_lock(self.camera):
            result = self.run_tune()
            self.assertIn('Another tuning', result.message)
            with self.assertRaisesRegex(RuntimeError, 'Another tuning'):
                a.undo(self.camera)
        self.assertEqual(self.camera.writes, [])
        self.assertEqual(self.camera.brightness, 47)

    def test_requested_137_to_155(self):
        result = self.run_tune(137, 155)
        self.assertTrue(result.changed)
        self.assertEqual((result.before.median, result.after.median), (137, 155))
        self.assertEqual(self.camera.value, 10)

    def test_rejected_clipped_candidate_keeps_best(self):
        def capture(camera, timeout):
            if camera.value >= 11:
                return burst(255)
            return burst(137 + (camera.value-9)*5)
        result = a.run(self.camera, capture_frames=capture, detect=self.detect)
        self.assertTrue(result.changed)
        self.assertEqual(self.camera.value, 10)
        self.assertEqual(result.after.median, 142)
        self.assertEqual(self.camera.brightness, 47)

    def test_trial_budget_and_control_bounds(self):
        captures = []
        def capture(camera, timeout):
            captures.append((camera.value, camera.brightness))
            return burst(100 + (camera.value-9)*2 + (camera.brightness-47)*2)
        result = a.run(self.camera, capture_frames=capture, detect=self.detect)
        self.assertTrue(result.changed)
        self.assertLessEqual(len(captures), 7)
        self.assertLessEqual(abs(self.camera.value-9), 3)
        self.assertLessEqual(abs(self.camera.brightness-47), 6)

    def test_sleeping_does_not_capture_or_write(self):
        snapshot = self.camera.snapshot
        self.camera.snapshot = lambda: dict(snapshot(), status={'sleeping': True})
        with patch.object(a, 'capture') as capture:
            result = a.run(self.camera, capture_frames=capture, detect=self.detect)
        self.assertIn('Wake the camera', result.message)
        capture.assert_not_called()
        self.assertEqual(self.camera.writes, [])

    def test_unclipped_face_can_use_highlight_allowance(self):
        before = a.Metrics(137, 0, 0, (30, 30, 120, 120))
        for clipping, accepted in ((.01, True), (.023, False)):
            self.camera.value = 9
            self.camera.brightness = 47
            after = a.Metrics(155, clipping, 0, before.face)
            with patch.object(a, 'measure_burst', side_effect=[before, after]):
                result = self.run_tune()
            self.assertEqual(result.changed, accepted)
            self.assertEqual(self.camera.value, 10 if accepted else 9)

    def test_clipped_baseline_requires_highlight_recovery(self):
        before = a.Metrics(137, .1, 0, (30, 30, 120, 120))
        after = a.Metrics(155, .1, 0, before.face)
        with patch.object(a, 'measure_burst', side_effect=[before, after]):
            result = self.run_tune()
        self.assertFalse(result.changed)
        self.assertEqual(self.camera.value, 9)
        self.assertEqual(self.camera.brightness, 47)

    def test_custom_target_validation(self):
        for value in (99, 181, True, 155.0):
            with self.assertRaises(ValueError):
                a.TuneOptions(value)
        result = self.run_tune(137, 140, options=a.TuneOptions(140))
        self.assertFalse(result.changed)


if __name__ == '__main__':
    unittest.main()
