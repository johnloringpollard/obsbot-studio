# Person segmentation model

`selfie_segmenter.tflite` is Google's MediaPipe Selfie Segmenter, float16 version 1, distributed under Apache 2.0. The license is in `LICENSE-SelfieSegmenter`.

Source: https://developers.google.com/edge/mediapipe/solutions/vision/image_segmenter

Download: https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/1/selfie_segmenter.tflite

SHA-256: `191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b`

The model runs locally through OpenCV 5's TensorFlow Lite importer. MediaPipe's Python runtime is not required. No images are sent to a service. Run `python scripts/install_effects_model.py` to restore the pinned model if needed.
