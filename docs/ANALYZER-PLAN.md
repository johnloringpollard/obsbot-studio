# One-shot camera tuning and packaging

- [x] Read pstack and relevant principles: Model the Domain, Experience First, Prove It Works, Separate Before Serializing Shared State.
- [x] Trace current flow: UI dispatches serialized CameraWorker operations; Camera validates fresh descriptors and reads back UVC writes; Preview owns a separate FFmpeg process. Recording blocks settings edits. Effects modify preview and recordings only.
- [x] Compare designs. Continuous preview feedback risks tuning transformed pixels and conflicts with recording. A bounded worker captures raw MJPEG after stopping preview, tests a small hardware exposure adjustment, restores on failure, and returns a report. Choose the bounded worker.
- [x] Blocking first steps: inspect camera controls, capture ownership, and GitHub identity before tests/publish.
- [x] Independent workstreams: read-only official-camera research; isolated analyzer implementation; lead owns hardware and packaging.
- [x] Shared mutable state: worker writes only /tmp/obsbot-analyzer-worker; lead alone touches live camera and integrates files.
- [x] Smallest safe decomposition: one worker owns analyzer plus UI integration to keep lifecycle changes together.
- [x] Implement named analysis/report data, bounded tuning, persistent undo, and meaningful synthetic tests.
- [x] Verify unit/UI tests and real camera guards/no-op; temporary exposure readback and restoration passed. Accepted automatic improvement remains covered by synthetic tests, not demonstrated on the live healthy scene.
- [x] Independent fresh-context review found dropped debounced Effects edits during camera operations. Fixed by flushing before busy state; regression and targeted independent recheck passed.
- [x] Package generic installation, deliberate screenshot, dependency/model attribution, and privacy audit.
- [x] Publish new public GitHub repository and verify main commit and screenshot via GitHub API. PR step n/a: new standalone repository explicitly requested.

The reference screenshot alone cannot establish a matched lighting comparison. Raw camera capture format, ISP processing, focus, exposure and software effects are separate variables. Do not promise aesthetic equivalence or represent synthetic tests as hardware verification.
