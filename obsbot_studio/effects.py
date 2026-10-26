"""CPU image effects shared by preview and recording."""
from dataclasses import dataclass, fields
from pathlib import Path
import math
import re



@dataclass(frozen=True)
class EffectSettings:
    background: str = 'off'
    blur: int = 25
    background_path: str = ''
    background_color: str = '#30343b'
    gamma: float = 1.0
    filter: str = 'original'
    overlay_path: str = ''
    overlay_opacity: int = 100
    overlay_scale: int = 20

    def __post_init__(self):
        if self.background not in ('off', 'blur', 'image', 'color'):
            raise ValueError('Invalid background mode')
        if self.filter not in ('original', 'mono', 'warm', 'cool'):
            raise ValueError('Invalid filter')
        for name, low, high in [('blur', 0, 100), ('overlay_opacity', 0, 100), ('overlay_scale', 5, 100)]:
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} must be an integer from {low} to {high}')
        if type(self.gamma) not in (int, float) or not math.isfinite(self.gamma) or not .5 <= self.gamma <= 2:
            raise ValueError('gamma must be from 0.5 to 2')
        for name in ('background_path', 'overlay_path', 'background_color'):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f'{name} must be a string')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', self.background_color):
            raise ValueError('background_color must be #RRGGBB')
        if self.background == 'image' and not self.background_path:
            raise ValueError('Choose a background image')

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict):
            raise ValueError('Effects settings must be a JSON object')
        unknown = values.keys() - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f'Unknown effects settings: {", ".join(sorted(unknown))}')
        return cls(**values)

    @property
    def active(self):
        return self.background != 'off' or self.gamma != 1 or self.filter != 'original' or bool(self.overlay_path)


def _load_image(filename, alpha=False):
    import av
    path = Path(filename).expanduser()
    if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError(f'Image must be a file smaller than 20 MiB: {path}')
    try:
        with av.open(str(path)) as probe:
            stream = probe.streams.video[0]
            width, height = stream.codec_context.width, stream.codec_context.height
            if not width or not height or max(width, height) > 8192 or width * height > 32_000_000:
                raise ValueError('Image dimensions exceed 32 megapixels / 8192 pixels')
    except Exception as exc:
        raise ValueError(f'Cannot read image: {path}: {exc}') from exc
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] not in (3, 4) or max(image.shape[:2]) > 8192 or image.shape[0] * image.shape[1] > 32_000_000:
        raise ValueError(f'Unsupported image or image exceeds 32 megapixels / 8192 pixels: {path}')
    if image.dtype != np.uint8:
        raise ValueError(f'Image must use 8-bit color: {path}')
    if alpha:
        if image.shape[2] != 4:
            raise ValueError('Overlay must be a PNG image with an alpha channel')
        if path.suffix.lower() != '.png':
            raise ValueError('Overlay must be a PNG image')
        return image
    return image[:, :, :3]


def _cover(image, width, height):
    source_height, source_width = image.shape[:2]
    if source_width * height > source_height * width:
        crop_width = max(1, round(source_height * width / height))
        left = (source_width - crop_width) // 2
        image = image[:, left:left + crop_width]
    else:
        crop_height = max(1, round(source_width * height / width))
        top = (source_height - crop_height) // 2
        image = image[top:top + crop_height]
    return cv2.resize(image, (width, height))


class Processor:
    def __init__(self, settings, model_path=None):
        global cv2, np
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError('Effects require OpenCV and NumPy; run the installer') from exc
        self.settings = settings
        self.net = None
        self._cached_size = None
        self._cached_background = None
        self._cached_overlay = None
        if settings.background != 'off':
            path = Path(model_path) if model_path else Path(__file__).resolve().parents[1] / 'models' / 'selfie_segmenter.tflite'
            if not path.is_file():
                raise ValueError(f'Person segmentation model is missing: {path}')
            if not hasattr(cv2.dnn, 'readNetFromTFLite'):
                raise RuntimeError('Background effects require OpenCV 5 with TensorFlow Lite support')
            try:
                self.net = cv2.dnn.readNetFromTFLite(str(path))
            except cv2.error as exc:
                raise ValueError(f'Cannot load person segmentation model: {path}') from exc
        self.background = _load_image(settings.background_path) if settings.background == 'image' else None
        self.overlay = _load_image(settings.overlay_path, alpha=True) if settings.overlay_path else None
        self.lut = np.clip((np.arange(256) / 255) ** (1 / settings.gamma) * 255, 0, 255).astype(np.uint8)

    def _mask(self, frame):
        blob = cv2.dnn.blobFromImage(frame, 1 / 255, (256, 256), swapRB=True)
        self.net.setInput(blob)
        probability = self.net.forward()[0, 0]
        mask = cv2.resize(probability, (frame.shape[1], frame.shape[0]))
        # Confident foreground is exactly opaque; interpolation softens only the boundary.
        return np.clip((mask - .2) / .6, 0, 1)[:, :, None]

    def process(self, bgr):
        if not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3 or not bgr.size:
            raise ValueError('Expected a nonempty uint8 BGR frame')
        s = self.settings
        if not s.active:
            return bgr
        height, width = bgr.shape[:2]
        result = bgr
        if s.background != 'off':
            size = (width, height)
            if self._cached_size != size:
                self._cached_size = size
                self._cached_background = None
            mask = self._mask(bgr)
            if s.background == 'blur':
                if s.blur:
                    scale = min(1, 320 / width)
                    small = cv2.resize(bgr, (max(1, round(width * scale)), max(1, round(height * scale))))
                    small = cv2.GaussianBlur(small, (0, 0), max(.1, s.blur * .3 * scale))
                    background = cv2.resize(small, (width, height))
                else:
                    background = bgr
            elif s.background == 'image':
                if self._cached_background is None:
                    self._cached_background = _cover(self.background, width, height)
                background = self._cached_background
            else:
                color = tuple(int(s.background_color[i:i + 2], 16) for i in (5, 3, 1))
                if self._cached_background is None:
                    self._cached_background = np.full_like(bgr, color)
                background = self._cached_background
            weight = mask[:, :, 0]
            result = cv2.blendLinear(bgr, background, weight, 1 - weight)
        if s.gamma != 1:
            result = cv2.LUT(result, self.lut)
        if s.filter == 'mono':
            result = cv2.cvtColor(cv2.cvtColor(result, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        elif s.filter in ('warm', 'cool'):
            multipliers = (.9, 1, 1.1) if s.filter == 'warm' else (1.1, 1, .9)
            result = np.clip(result.astype(np.float32) * multipliers, 0, 255).astype(np.uint8)
        if self.overlay is not None:
            scale = min(width * s.overlay_scale / 100 / self.overlay.shape[1], height / self.overlay.shape[0])
            overlay_size = (max(1, round(self.overlay.shape[1] * scale)), max(1, round(self.overlay.shape[0] * scale)))
            if self._cached_overlay is None or self._cached_overlay.shape[1::-1] != overlay_size:
                self._cached_overlay = cv2.resize(self.overlay, overlay_size)
            overlay = self._cached_overlay
            oh, ow = overlay.shape[:2]
            result = result.copy()
            region = result[height - oh:, width - ow:]
            alpha = overlay[:, :, 3:4].astype(np.float32) / 255 * s.overlay_opacity / 100
            region[:] = np.clip(region * (1 - alpha) + overlay[:, :, :3] * alpha, 0, 255).astype(np.uint8)
        return result
