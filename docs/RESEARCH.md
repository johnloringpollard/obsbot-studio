# Tiny 3 Linux capability reference

Research date: October 24, 2026. Target: USB 3564:ff02, OBSBOT Tiny 3. This app is independent of OBSBOT and does not include its proprietary SDK.

## Official application and camera features

The supplied Mac screenshots and [Tiny 3 product specification](https://www.obsbot.com/obsbot-tiny-3-series-4k-ptz-webcam/specs) describe 4K30 and 1080p120 capture, HDR, autofocus, face exposure, ISO 100–12800 and a directional microphone array. The Linux device advertises those high-resolution modes as MJPEG. Its uncompressed YUYV modes are limited to 640×480 or 640×360. The app selects MJPEG explicitly.

[OBSBOT Center](https://www.obsbot.com/download/obsbot-tiny-3-series) is offered for Windows and macOS. The [official Linux SDK page](https://www.obsbot.com/sdk) lists Tiny 3 compatibility and requires an account/application for delivery by email. No application or email was sent during this work.

### Coverage

| Mac feature | Linux app | Evidence / limit |
|---|---|---|
| Live view, capture resolution/frame rate | Implemented | MJPEG modes from actual device; display capped at 1280 pixels wide / 30 fps |
| 4K30, 1080p30/60/120, 720p30/60/120 | Implemented | Actual camera formats checked; recordings retain selected resolution |
| High-fps normal / slow-motion recording | Implemented | One capture process feeds preview and MP4; slow motion plays at 30 fps |
| Recording audio | Implemented | Explicit named Pulse/PipeWire source, default Off; actual Tiny 3 microphone tested with 4K video; slow motion stays silent |
| Snapshot | Implemented | Saves displayed 1280-pixel preview frame, not full-resolution still capture |
| HDR | Implemented | Device change/readback/restore passed |
| Autofocus, manual focus, global / face priority | Implemented | UVC focus controls; vendor face-priority round-trip passed |
| Auto/manual exposure, global / face priority | Implemented | UVC exposure controls; vendor face-priority round-trip passed |
| Exposure compensation, anti-flicker, shutter, gain | Implemented | Advertised UVC ranges; gain uses device units, not a claimed ISO conversion |
| Auto white balance, temperature, red/blue gains | Implemented | Device UVC controls; last-written temperature/gain controls interact |
| Brightness, contrast, saturation, hue, sharpness | Implemented | Device UVC controls; brightness round-trip passed |
| Pan, tilt, zoom | Implemented | Driver setpoints; tilt limited to documented −60° to +32° controllable range |
| Wide/medium/narrow field of view | Implemented | Device round-trip passed; tracking can change framing independently |
| Single/group tracking | Implemented command transport | Group readback passed. Single returned Off with an empty chair, then stayed in mode 2 with the user in view |
| Human full/upper/close/headless/lower framing | Implemented command transport | Normal, upper-body and close-up state changes passed with the user in view; headless/lower-body modes were not separately exercised |
| Hand/whiteboard/desk tracking | Visible, disabled | SDK mode values documented; no live test of those behaviors |
| Mirror | Implemented | Device round-trip passed |
| Sleep / wake | Implemented | Both state changes passed; preview wakes camera |
| Auto-sleep timer | Visible, disabled | Device disconnected during timer test; exact SDK packet was confirmed, firmware cause unresolved |
| Microphone enable, AGC, pickup distance, mic while asleep | Implemented | All device round-trips passed; these are not spatial-audio presets |
| Four local setting presets | Implemented | App-local JSON, not the camera's three hardware PTZ presets; sleep and timer excluded |
| ISO lower/upper bounds | Visible, disabled | No verified Tiny 3 API; gain is not an ISO-range substitute |
| Standard / Streaming image styles | Visible, disabled | Exact Tiny 3 implementation and payload unverified |
| White-balance tint/shift, custom exposure curves | Visible, disabled | No verified device command; software gamma is in Effects |
| Zone boundaries, Only Me, composition, object selection, tracking speed | Visible, disabled | Need exact Tiny 3 commands and behavioral checks |
| Sound-source assisted tracking | Visible, disabled | Requires voice-localization control; microphone AGC does not enable it |
| Voice / gesture controls | Visible, disabled | SDK IDs differ between releases; no guessed writes |
| Pure/Spatial/Smart Omni/Directional/Dual-Directional audio | Visible, disabled | No verified Tiny 3 payload or mode readback |
| Background blur / replacement, gamma, filters, PNG overlay | Implemented locally | Effects tab; processed preview, snapshot and recording at 720p30 |
| Face retouching / Eye Contact | Visible, disabled | Proprietary processing remains unavailable |
| Teleprompter | Implemented | Separate reading window, not included in recordings |
| Multiple-camera PiP / multiview | Visible, not implemented | Requires a separate camera-mixing workflow |
| Indicator brightness | Implemented | Actual Tiny 3 readback 3→2→3 passed |
| Firmware / factory reset | Visible, disabled | Official Center required |

No claim of complete OBSBOT Center parity is made. Disabled rows explain their status in the interface. The next hardware parity step is obtaining the current official Tiny 3 Linux SDK documentation for the missing controls, then testing their readback and behavior individually. Host effects need an actual video-processing and virtual-camera implementation even after camera control parity.

## Screenshot and UI references

- User-provided Mac Console and Image screenshots, October 24.
- [OBSBOT Center Lite mode](https://www.obsbot.com/explore/obsbot-center/obsbot-center-lite-mode).
- [Multi-device interface](https://www.obsbot.com/explore/obsbot-center/multi-device-version-update).
- [Beauty effects guide and screenshots](https://www.obsbot.com/explore/obsbot-center/apply-beauty-effects-in-third-party-software). These effects require Center's virtual-camera output to reach other apps.
- [OSC documentation](https://www.obsbot.com/explore/obsbot-center/osc). Tiny-series OSC is a bridge through running OBSBOT Center, not a standalone camera endpoint for Linux.

The Mac interface's top numbered slots select devices. This app labels its different feature “Local presets” to avoid confusing the two.

## Protocol evidence

Standard controls use `v4l2-ctl`. Vendor controls use UVC extension unit 2, status/TLV selector 6 and framed command selector 2. Readback is mandatory after writes. Initial settings are saved before any writes.

- [Tiny 3 Lite protocol](https://github.com/joshualambert/obsbot-tiny3-linux/blob/main/PROTOCOL.md). Its hardware is USB ff04, so full Tiny 3 support was not assumed.
- [Tiny 2 protocol reference](https://github.com/lxman/obsbot-mcp/blob/main/tiny2_specification.md).
- [SDK declarations](https://github.com/aaronsb/obsbot-camera-control/blob/main/sdk/v1.0.2/include/dev/dev.hpp) and the locally installed SDK binary were inspected to cross-check packet layout. No SDK binary was copied into this app.
- [OBSBOT4Linux Tiny 3 integration](https://github.com/vampyren/obsbot4linux/blob/main/qt/src/CameraController.cpp) documents Single mode disengaging when no person is acquired.

Auto-sleep's SDK encoding is `0b 02 <seconds:u16 little endian>`, padded to 60 bytes. The 180-second test coincided with USB disconnect and RNDIS/UVC re-enumeration. Reconnecting restored the original 120-second value. This does not isolate the firmware cause, so writes and preset restoration of the timer are blocked.

## Picture quality

The MJPEG/YUYV mode difference can explain a resolution difference, but it does not prove why this user's Mac image looked better. No matched Mac/Linux capture under identical light/settings was available. Mac virtual-camera effects, HDR, exposure, white balance, framing and downstream conferencing resolution can all affect the comparison. Settings in this app change the physical camera; preview scaling affects only this app's display/snapshot.

## Completed verification

The no-hardware suite covers protocol CRC/layout, invalid values, inactive controls, presets, recording finalization, synthetic audio/video, a preserved 400 ms input offset, stepped/keyboard slider interaction, deferred-command shutdown, and camera readback/error handling. An independent fresh-context review reproduced UI issues; the fixes and affected tests were rechecked.

Live captures passed full FFmpeg decode: 1080p60 normal, 1080p120 slowed to 30 fps, and 4K30 with the Tiny 3 microphone. The final 4K audio test produced 123 preview frames over a six-second wall-clock run including device startup, with successful MP4 finalization. Software audio timestamp alignment is tested; physical lip sync is not measured with a clap test. Final input queues are bounded to 16 video packets and 64 audio packets.

All vendor settings tested before final launch were restored. Sensor gain changed automatically from 4 to 6 under auto exposure; the app did not force it back into a manually chosen gain. Starting preview wakes the camera. Personal camera captures remain only in the ignored local evidence directory.

Correction: the user confirmed the Tiny 3 Image Style selector offers Standard and Streaming. Earlier UI copy incorrectly asserted host-side processing; that was not established and has been removed. Related Tail 2 protocol research identifies a camera-side live_style_en flag, but its command must not be assumed valid for Tiny 3. Exact Tiny 3 processing differences remain unverified.

## October 24 software effects extension

The app now supplies local person-segmented background blur, background image/solid-color replacement, gamma, monochrome/warm/cool filters, and transparent PNG overlays. These are independent Linux effects, not replicas of OBSBOT's proprietary Beauty or image-style algorithms. Effects share one composited output across preview, snapshots, and recorded video. They run at 1280x720 and up to 30 fps; the segmentation mask is calculated for each frame. Rapid motion and difficult lighting can still affect mask edges.

The source model is [Google MediaPipe Selfie Segmenter](https://developers.google.com/edge/mediapipe/solutions/vision/image_segmenter), Apache 2.0. Its local TensorFlow Lite file is checksum-pinned and runs through OpenCV 5. The MediaPipe Python runtime is not required. PyAV carries source timestamps into H264/AAC recording. Gamma and color filters are software adjustments and do not change the physical camera output.

Indicator brightness is implemented through selector 6 TLV `1a 01 <level>` with status byte 33. The installed SDK has a Tiny3-specific branch for that setter. Levels 3→2→3 passed hardware readback, with the original level restored. This does not rely on conflicting Tiny3 Lite status-offset documentation.

The teleprompter is a separate reading window with adjustable font and scrolling speed, pause, and reset. It is not included in saved media. Multiple camera PiP, multiview, neural face retouching, and Eye Contact remain unimplemented.

Virtual-camera output remains unavailable. Creating a dedicated loopback requires root access on this machine. The existing Hardware ISP and iPhone loopbacks remain untouched. Choosing the physical Tiny 3 directly in a calling application does not include software effects.


Final effects verification: the 40-second live capture with the Tiny 3 microphone displayed 1,007 processed preview frames at about 25.7 fps and saved a playable H264/AAC recording. All recorded stream timestamps increase. Audio extends about 0.81 seconds beyond the last video frame at shutdown; physical lip sync has not been measured. This limitation is distinct from the fixed overlapping-PCM startup failure. Deterministic effects, timestamp, interrupted-recording, resize-bound, UI, and full existing checks pass. Independent review findings were fixed and rechecked.
