# Picture quality and the Studio Display comparison

A camera's appearance depends on framing, lighting, exposure, white balance, optics, onboard processing and the application displaying it. Adding controls does not reproduce another manufacturer's image pipeline.

Apple documents noise-reduction, contrast and framing changes in the [Studio Display camera firmware notes](https://support.apple.com/en-ie/106345). The [original Studio Display](https://www.apple.com/newsroom/2022/03/apple-unveils-all-new-mac-studio-and-studio-display/) uses an A13 processor. Those facts do not identify which processing was active in a particular conference screenshot.

The [Tiny 3 specification](https://www.obsbot.com/obsbot-tiny-3-series-4k-ptz-webcam/specs) lists a 1/1.28-inch sensor, f/1.8 lens, HDR and high-resolution MJPEG output. This app explicitly selects MJPEG. Its preview scales to 1280 pixels wide; recordings retain the selected dimensions unless software effects are active.

## Local comparison, October 26, 2026

Both physical cameras were captured as 1920x1080 MJPEG within the same room and session. The camera positions and framing differed, so this was not a controlled sensor comparison. The Studio Display exposed the face more brightly. In the central half of each detected face, median grayscale values were 153 for Studio Display and 131 for Tiny 3. At least one color channel reached 250 in about 1.8% of that Studio Display region versus 0% for Tiny 3. These measurements describe those frames, not camera quality in general.

Tiny 3 had HDR and face-priority exposure/focus enabled. Its white balance was manual with custom red/blue gains. A reported temperature of 2000 K alone did not describe the effective color processing because the last-written channel gains can override temperature tuning on this firmware. The analyzer therefore preserves those settings.

## What the analyzer can change

The analyzer checks face exposure in a settled burst. It tests exposure compensation first, then small hardware-brightness changes if compensation stops helping. It retains measured improvements and restores rejected changes. It does not calculate a desired skin color, infer a white point from skin, or continuously retune the camera. Color calibration needs a known neutral reference under the same light.

The adjustable target defaults to 155 with a tolerance of seven grayscale levels. This is an explicit aesthetic preference, not an inferred ideal for every skin tone. The check can still make mistakes. Use Undo or the manual exposure slider if its result does not suit you. A healthy image can produce a no-change result even when you prefer a brighter look.

## Controls still unavailable

Standard/Streaming image styles, ISO limits, white-balance tint and custom camera curves remain disabled. Their Tiny 3 command formats and behavior are not verified. Software gamma and color filters do not replicate those modes. The full [capability reference](RESEARCH.md) distinguishes working controls from unavailable ones.

For calls, hardware adjustments affect the physical camera output. Software blur and filters currently affect this app's preview and recordings only. A separate virtual-camera output would be needed to send those effects to a calling app.

## Verification limits

The October 26 live checks confirmed asleep/moving/unsettled guards, a healthy-face no-change result, and manual compensation readback/restoration. The initial severe-exposure-only version did not trigger an accepted automatic adjustment. Accepted improvement, failed trials, repeated tuning, persistent Undo and restoration failures are covered by deterministic tests with fake camera controls. These tests are not a claim that the analyzer improves every real room or face.

The portrait tuner uses an eight-second capture timeout and checks a 60-second analysis deadline. Existing camera-command timeouts and emergency restoration can take additional time. The worker keeps the interface responsive while it completes restoration.

## Portrait tuner follow-up

The user's second pair of screenshots had face-region medians of 177 for Studio Display and 137 for Tiny 3. About 31% of the measured Studio Display face crop had at least one color channel at or above 250; none did in the Tiny 3 crop. The default target of 155 aims for a brighter face with more highlight headroom than that reference. These are screenshot measurements, not a calibrated or simultaneous sensor comparison.

The new live run measured 137 → 148 toward target 155, with 0% measured face clipping before and after. Exposure compensation remained 9; hardware brightness changed 47 → 51. White balance and red/blue gains stayed unchanged. An earlier run detected face movement after making trials and restored the starting controls. Undo was separately applied and verified, then the accepted result was reapplied with Undo retained.

The test demonstrates a useful exposure improvement in this scene. It does not establish that the Tiny 3 is objectively better than Studio Display, or that every lighting setup reaches its requested target. The older conservative-tuner evidence above describes version 0.1.0; the iterative portrait tuner is version 0.2.0.
