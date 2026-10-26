# OBSBOT Studio for Linux

## Goal and scope
Build a runnable local Linux desktop control application for John's USB Tiny 3, styled after the supplied dark OBSBOT Center screenshots. Provide real camera controls and live preview, preserve/recover the pre-test settings, inventory Mac features and expose unsupported controls with an honest explanation rather than pretending they work. No firmware flashing, no cloud uploads, no external messages.

Completion predicates: app launches from the desktop; detects the actual Tiny 3; preview displays real frames; supported camera changes can be read back; deterministic input/boundary tests pass; live control round-trip restores baseline; unsupported features and picture-quality limitations documented; independent completion review addressed.

## Phases
- [x] Read poteto principles and investigation/architecture/figure-it-out workflows.
- [x] Record standard UVC baseline before any mutation.
- [x] Research official Mac feature set and screenshots, SDK and public Linux protocol.
- [x] Compare native Qt controls with local browser control service and select architecture.
- [x] Implement bounded camera interface, discovery, capture, backups and verified control operations.
- [x] Build Console, Image, More and recording/preview views with capability-aware states.
- [x] Verify on hardware: before/after readback, preview and recordings, restoration.
- [x] Fresh-context independent review and fixes.
- [x] Install local launcher, leave app accessible, document tested vs unavailable features.

## Work ownership
Lead owns hardware writes, backend and integration. Two read-only researchers cover protocol and Mac feature inventory. Any UI worker gets an isolated directory and an explicit backend contract. No concurrent hardware experiments.

Full Mac parity remains incomplete for the disabled features enumerated in RESEARCH.md. Current Linux build and documented verification scope are complete.
