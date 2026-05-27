from __future__ import annotations

import os
import sys


def detect_device() -> tuple[str, str]:
    """Returns (device, compute_type). Priority: CUDA > MPS > CPU."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
        if torch.backends.mps.is_available():
            # MPS does not support float16 in ctranslate2
            return "mps", "float32"
    except ImportError:
        pass
    return "cpu", "int8"


def resolve_hf_token(cli_token: str | None) -> str:
    token = cli_token or os.environ.get("HUGGINGFACE_TOKEN", "")
    if not token:
        sys.exit(
            "Error: HuggingFace token required for diarization.\n"
            "Set HUGGINGFACE_TOKEN env var or pass --hf-token TOKEN.\n"
            "Note: you must also accept the pyannote model license at "
            "https://huggingface.co/pyannote/speaker-diarization-3.1"
        )
    return token
