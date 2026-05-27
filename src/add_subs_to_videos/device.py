from __future__ import annotations

import os


def detect_device() -> tuple[str, str]:
    """Returns (device, compute_type). Priority: CUDA > CPU.

    MPS is skipped: whisperx's alignment model raises ValueError: unsupported device mps.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


def resolve_hf_token(cli_token: str | None) -> str | None:
    return cli_token or os.environ.get("HUGGINGFACE_TOKEN") or None
