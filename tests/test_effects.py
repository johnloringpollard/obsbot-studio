import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from obsbot_studio.effects import EffectSettings, Processor, _cover


class EffectsTest(unittest.TestCase):
    def test_validation(self):
        for values in [{'oops': 1}, {'blur': True}, {'blur': 101}, {'gamma': float('nan')}, {'background': 'oops'}, {'background': 'image'}, {'overlay_scale': 0}, {'background_color': 'red'}, {'filter': 'beauty'}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                EffectSettings.from_dict(values)

    def test_off_exact_and_filters(self):
        frame = np.random.default_rng(0).integers(0, 256, (24, 32, 3), dtype=np.uint8)
        self.assertIs(Processor(EffectSettings()).process(frame), frame)
        mono = Processor(EffectSettings(filter='mono')).process(frame)
        np.testing.assert_array_equal(mono[:, :, 0], mono[:, :, 2])
        self.assertGreater(Processor(EffectSettings(gamma=2)).process(frame).mean(), frame.mean())

    def test_foreground_preserved_background_replaced(self):
        frame = np.full((24, 32, 3), 120, np.uint8)
        with patch('obsbot_studio.effects.Path.is_file', return_value=True), patch('cv2.dnn.readNetFromTFLite'):
            processor = Processor(EffectSettings(background='color', background_color='#ff0000'))
        mask = np.zeros((24, 32, 1), np.float32)
        mask[6:18, 8:24] = 1
        processor._mask = lambda unused: mask
        result = processor.process(frame)
        np.testing.assert_array_equal(result[6:18, 8:24], frame[6:18, 8:24])
        np.testing.assert_array_equal(result[0, 0], [0, 0, 255])

    def test_cover_extreme_aspects_allocate_only_target_size(self):
        Processor(EffectSettings())
        for shape in [(1, 8192, 3), (8192, 1, 3), (10, 20, 3)]:
            with self.subTest(shape=shape):
                image = np.full(shape, 137, np.uint8)
                with patch('cv2.resize', wraps=cv2.resize) as resize:
                    result = _cover(image, 1280, 720)
                self.assertEqual(result.shape, (720, 1280, 3))
                self.assertEqual(resize.call_count, 1)
                self.assertEqual(resize.call_args.args[1], (1280, 720))
                self.assertTrue(np.all(result == 137))

    def test_constant_image_blur_preserves_soft_boundaries(self):
        frame = np.full((24, 32, 3), 137, np.uint8)
        with patch('obsbot_studio.effects.Path.is_file', return_value=True), patch('cv2.dnn.readNetFromTFLite'):
            processor = Processor(EffectSettings(background='blur', blur=100))
        mask = np.broadcast_to(np.linspace(0, 1, 32, dtype=np.float32)[None, :, None], (24, 32, 1)).copy()
        processor._mask = lambda unused: mask
        np.testing.assert_array_equal(processor.process(frame), frame)

    def test_overlay_alpha_and_cover(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'logo.png'
            image = np.full((10, 10, 4), (0, 0, 255, 128), np.uint8)
            cv2.imwrite(str(path), image)
            result = Processor(EffectSettings(overlay_path=str(path), overlay_scale=50)).process(np.zeros((20, 20, 3), np.uint8))
            np.testing.assert_array_equal(result[0, 0], [0, 0, 0])
            self.assertEqual(int(result[-1, -1, 2]), 128)
            with self.assertRaises(ValueError):
                Processor(EffectSettings(overlay_path=str(Path(root) / 'missing.png')))

if __name__ == '__main__':
    unittest.main()
