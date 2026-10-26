# Remaining Linux features

## Task list
- [x] Read pstack principles. Experience First prioritizes usable effects; Prove It Works requires actual rendered and recorded output.
- [x] Ground the capture path: Preview owns one FFmpeg process for camera input, direct MP4, and MJPEG preview. Qt owns camera controls on a separate worker. No software effects currently reach recordings or other apps.
- [x] Compare two effects designs and settle a bounded data/processing contract.
- [x] Blocking first steps: verify segmentation runtime/model and camera protocol evidence before enabling controls.
- [x] Independent workstreams: read-only hardware capability audit and effects architecture; code owners assigned after the contract.
- [x] Shared mutable state: lead owns all camera experiments; implementation workers use isolated copies, not shared files.
- [x] Smallest safe decomposition: one effects core owner and one UI integration owner; serialize integration.
- [x] Implement feasible controls/effects, with unsupported proprietary features left explicit.
- [x] Run deterministic tests, real captures, visual inspection, recording validation and shutdown checks.
- [x] Fresh-context independent review; fix supported findings and repeat affected checks.
- [x] Document capabilities and open the updated app.
- [x] Ordered commits/PR: not requested; preserve local project and provide reviewable files instead.

## Constraints
No guessed vendor commands, firmware/reset operations, or auto-sleep writes. Keep existing direct high-resolution capture and timing behavior when effects are off. Local video stays local. No cloud inference. Do not capture other cameras or overwrite existing virtual-camera devices.

## Chosen design

Compared two complete shapes: a Python worker using PyAV and OpenCV DNN, and a native FFmpeg frei0r filter using OpenCV C++. The native filter keeps FFmpeg timing ownership but introduces a compiled plugin and packaging. The Python worker fits this app and its tests; choose it with a single timestamped input and shared composited preview/recording output. The existing direct FFmpeg path remains unchanged when effects are off.

`EffectSettings` is an immutable configuration snapshot. `Processor.process(bgr)` applies segmentation, background composition, gamma, filters and overlay. `effects_capture` owns decoding, timing and MP4 finalization in a separate process. Qt remains responsible only for process lifecycle and controls. Settings changes restart a preview session after debounce; recording freezes settings. Effects output is explicitly 1280x720 at up to 30 fps.

Architecture review rejected preview-only effects because recordings would remain raw, and rawvideo frame-count timestamps because processing stalls would change elapsed time. Preserve source timestamps and audio offsets instead. No raw fallback on processing failure.

## Hardware audit

Indicator brightness uses Tiny3-specific SDK selector 6 TLV `1a 01 <level>`, status byte 33, range 0–3. Real-camera level 3→2→3 readback passed on October 24 and restored the baseline. Other missing image-style, voice, spatial audio and gesture features lack sufficient matching Tiny3 declarations/readback. Do not substitute older model semantics.

A dedicated virtual camera cannot currently be created: `/dev/v4l2loopback` requires root, and noninteractive sudo requires a password. Nodes 50 and 51 belong to Hardware ISP Camera and iPhone Camera. They remain untouched.


## Verification corrections

The first OpenCV Zoo model failed visual acceptance because it blurred part of the user's face. Replaced it with Google's official Selfie Segmenter through OpenCV 5's TensorFlow Lite importer. Direct OpenCV inference needs no MediaPipe Python runtime. A temporary MediaPipe package probe was removed after failing, together with its newly installed dependencies. The chosen model preserves facial detail in the checked source frame and calculates a mask per frame.

The real Tiny 3 microphone exposed overlapping initial PCM timestamps that synthetic regular timestamps missed. FFmpeg now normalizes audio with `aresample=async=1:first_pts=0:min_hard_comp=0.01`. A synthetic reproduction proves the unfiltered AAC failure, preserved 99 ms tone offset, and corrected end time within AAC padding.

Independent review found recoverable recordings were deleted after runtime errors and extreme-aspect background images could allocate oversized intermediate images. Failure cleanup now retains footage after any frames were captured; background images are cropped before resizing. Regression tests cover both findings. Targeted reviewer recheck found no remaining actionable issue. Physical lip sync has not been measured.


## Final checks

`evidence/remaining-tests-final.txt` records the complete no-hardware suite passing. `evidence/effects-live-1792875246574114559.json` records the final 40-second camera-and-microphone test: 1,007 displayed processed frames, about 25.7 preview fps, finalized H264/AAC MP4. All 1,024 video frames and 1,831 audio frames decode with strictly increasing timestamps. FFmpeg full decode using the source time base passes. The final capture uses four OpenCV threads and fast encoding to reduce backlog.

Audio ends about 0.81 seconds after video in the final test. This is a remaining end-of-capture verification limit; no physical clap/lip-sync test was performed. Do not describe decode success as proof of perfect physical sync. The effects pipeline preserves source timestamps and retains interrupted recordings for recovery.

The updated launcher uses the isolated runtime. The app is open on workspace 2 with the Effects tab selected and effects off, ready for the user to choose a background mode. The final UI screenshot is `evidence/remaining-features-ui.png`.
