#!/usr/bin/env bash
# One-time setup (Linux/macOS). Needs Python 3.10+.
set -e
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium          # or: export CHROME_PATH=/path/to/chromium
# Devanagari fonts (Ubuntu/Debian) - REQUIRED, the config uses these family names:
#   sudo apt-get install -y fonts-noto-core fonts-noto-extra fonts-lohit-deva fonts-deva-extra fonts-gargi fonts-sarai fonts-nakula
#   (fonts-deva-extra provides Kalimati/Samanata/Chandas; unused ones are harmless). Remove a family from config `fonts:` if you cannot install it.
python main.py info
python tests/test_pipeline_smoke.py && python tests/test_verifier.py
