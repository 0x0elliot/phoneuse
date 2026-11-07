#!/bin/sh
# Local screen-reading models for `phone text` / `phone find`: RapidOCR (PP-OCRv6)
# and GoClick-Large (GUI grounding). Separate venv: GoClick needs transformers 4.45.
set -e
cd "$(dirname "$0")/.."
uv venv -q --python 3.12 .venv-vision
# --no-cache: a corrupted uv cache once installed tqdm/packaging as empty dirs
uv pip install -q --no-cache --python .venv-vision/bin/python torch "transformers==4.45.0" \
    timm einops huggingface_hub rapidocr onnxruntime pillow numpy
.venv-vision/bin/python -c "
from huggingface_hub import snapshot_download
snapshot_download('HongxinLi/GoClick-Large', allow_patterns=['*.json', '*.py', 'model.safetensors'])"
echo "vision models ready"
