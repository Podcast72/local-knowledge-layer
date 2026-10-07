"""EmbeddingGemma 2 text-only loader, with all caches inside the project."""
from __future__ import annotations

import os
import time
from pathlib import Path

from .core import DIMENSIONS, ROOT

MODEL_ID = "google/embeddinggemma-2"
CACHE = ROOT / "models" / "huggingface"


def configure_environment() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    values = {
        "HF_HOME": CACHE,
        "HF_HUB_CACHE": CACHE / "hub",
        "HF_XET_CACHE": CACHE / "xet",
        "HF_ASSETS_CACHE": CACHE / "assets",
        "SENTENCE_TRANSFORMERS_HOME": CACHE / "hub",
        "XDG_CACHE_HOME": ROOT / ".cache",
        "TORCH_HOME": ROOT / ".cache" / "torch",
    }
    for key, value in values.items():
        os.environ[key] = str(value)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def backend() -> tuple[str, str, bool]:
    import torch
    available = bool(torch.backends.mps.is_available())
    return ("mps" if available else "cpu", "float32", available)


def load_model():
    configure_environment()
    import torch
    from sentence_transformers import SentenceTransformer

    device, dtype, _ = backend()
    start = time.perf_counter()
    model = SentenceTransformer(
        MODEL_ID,
        cache_folder=str(CACHE / "hub"),
        device=device,
        config_kwargs={"vision_config": None, "audio_config": None},
        model_kwargs={"torch_dtype": torch.float32},
    )
    elapsed = time.perf_counter() - start
    return model, device, dtype, elapsed


def embedder(model):
    def encode(texts: list[str], prompt_name: str):
        import gc
        import numpy as np
        import torch

        batches = []
        for start in range(0, len(texts), 64):
            batch = texts[start:start + 64]
            vectors = model.encode([{"text": value} for value in batch], prompt_name=prompt_name, truncate_dim=DIMENSIONS, normalize_embeddings=True,
                                   convert_to_numpy=True, show_progress_bar=False, batch_size=4)
            batches.append(np.asarray(vectors, dtype=np.float32))
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            gc.collect()
        return np.concatenate(batches, axis=0) if batches else np.empty((0, DIMENSIONS), dtype=np.float32)
    return encode
