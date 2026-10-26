"""Install the pinned MediaPipe Selfie Segmenter model after verifying its SHA-256."""
import hashlib
from pathlib import Path
import urllib.request

MODEL_SHA256 = "191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/1/selfie_segmenter.tflite"


def main():
    target = Path(__file__).resolve().parents[1] / "models" / "selfie_segmenter.tflite"
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == MODEL_SHA256:
        print("Person segmentation model is already installed and verified.")
        return
    with urllib.request.urlopen(MODEL_URL, timeout=30) as response:
        data = response.read(7_000_001)
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise RuntimeError("Model checksum mismatch. Existing model was not changed.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".download")
    temporary.write_bytes(data)
    temporary.replace(target)
    print(f"Installed verified person segmentation model: {target}")


if __name__ == "__main__":
    main()
