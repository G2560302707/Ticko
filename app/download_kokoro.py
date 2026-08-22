"""One-off local model fetch used during Ticko setup."""
from pathlib import Path

from huggingface_hub import hf_hub_download


root = Path(__file__).resolve().parent / "models" / "kokoro"
root.mkdir(parents=True, exist_ok=True)
repo = "onnx-community/Kokoro-82M-v1.1-zh-ONNX"
hf_hub_download(repo_id=repo, filename="onnx/model_int8.onnx", local_dir=root)
for voice in ("zf_001", "zf_006", "zf_021", "zf_036"):
    hf_hub_download(repo_id=repo, filename="voices/%s.bin" % voice, local_dir=root)
