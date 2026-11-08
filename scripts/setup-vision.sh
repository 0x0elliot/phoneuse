#!/bin/sh
# The local screen-reading model for `phoneuse text` and `tap-on`: RapidOCR (PP-OCRv6),
# in its own venv.
set -e
cd "$(dirname "$0")/.."
uv venv -q --python 3.12 .venv-vision
# --no-cache: a corrupted uv cache once installed tqdm/packaging as empty dirs
# onnxruntime-gpu runs OCR on an NVIDIA GPU (~0.18 s a screen against ~1.5 s on
# the CPU); it falls back to the CPU by itself when there is no GPU.
ORT=onnxruntime
command -v nvidia-smi >/dev/null 2>&1 && ORT=onnxruntime-gpu
uv pip install -q --no-cache --python .venv-vision/bin/python rapidocr "$ORT" pillow numpy
echo "vision model ready"
