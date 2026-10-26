#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
for command in python ffmpeg v4l2-ctl; do
  command -v "$command" >/dev/null || { echo "Missing $command. See the README installation instructions." >&2; exit 1; }
done
python - <<'PY'
try:
    import PySide6
    import cv2
    import numpy
except ImportError as error:
    raise SystemExit(f"Missing system dependency: {error}. Install the packages listed in README.md.")
if not hasattr(cv2.dnn, 'readNetFromTFLite'):
    raise SystemExit('Background effects require OpenCV 5 with the TensorFlow Lite importer.')
PY
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-effects.txt
.venv/bin/python scripts/install_effects_model.py
.venv/bin/python scripts/install.py
printf '\nInstalled. Open OBSBOT Studio from your application menu, or run obsbot-studio.\n'
