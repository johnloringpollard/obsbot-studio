# Portrait exposure tuning

- [x] Read pstack feature workflow and apply Experience First, Model the Domain, Prove It Works, and Separate Before Serializing Shared State.
- [x] Trace: UI serializes camera operations and stops preview; analyzer samples MJPEG, scores faces, writes controls through readback-verified Camera.apply, persists Undo. Current severe-underexposure threshold excludes the user's dimmer portrait.
- [x] Design comparison: reference-image color matching would conflate exposure, skin color, compression and ISP processing. Choose an explicit brightness preference with iterative raw-frame measurements and highlight guards. Keep white balance separate.
- [x] Blocking first steps: establish current settings and capture ownership before hardware trials.
- [x] Independent workstreams: one isolated worker owns analyzer/UI/tests; lead owns camera measurements, documentation, integration and release.
- [x] Shared mutable state: separate worker checkout; lead alone writes hardware. Tuner lock prevents two app instances tuning the same device at once.
- [x] Smallest safe decomposition: analyzer and UI stay with one worker because command arguments and persistent Undo must agree.
- [x] Implement target preference, bounded iterative exposure and brightness fallback, scoped multi-control Undo.
- [x] Test on current camera and verify readback, accepted image change, restoration, and failure behavior.
- [x] Independent fresh-context review and affected checks. Fixed QSettings test isolation; direct recheck confirms real preferences unchanged.
- [ ] Update documentation/screenshot, publish follow-up and verify remote contents.

Reference measurement: Studio Display screenshot face median 177, Tiny 3 screenshot 137. About 31% of the measured Studio Display face crop had a color channel at or above 250, compared with none in the Tiny 3 crop. A default target of 155 aims to lift the face while preserving highlight headroom. It is an adjustable aesthetic preference, not a universally correct skin-tone value. Neither screenshot establishes calibrated color or a controlled sensor comparison.

Live result: measured face brightness 137 → 148 with clipping 0% → 0%. Hardware brightness 47 → 51, compensation unchanged at 9. Late-motion failure restored original settings. Undo restored 47, then the accepted 51 was reapplied with Undo retained. All 36 analyzer tests and the complete non-hardware suite pass.
