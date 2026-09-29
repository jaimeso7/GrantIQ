"""Free, local semantic matching with an explicit offline failure mode.

Download the public model once with ``python -m grantiq.app.services.embeddings --download``.
Normal application requests only read local model files and never call an AI API.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import logging
import math
import os
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingUnavailable(RuntimeError):
    """The local model could not be loaded or used; caller must disclose fallback."""


class LocalEmbedder:
    """Lazily load MiniLM on CPU, with bounded reuse of normalized embeddings."""

    backend_name = "sentence-transformers/all-MiniLM-L6-v2 (local CPU)"

    def __init__(self, cache_dir: str | Path | None = None, *, allow_download: bool = False):
        self.cache_dir = Path(cache_dir or os.getenv("GRANTIQ_MODEL_CACHE", "data/models"))
        self.allow_download = allow_download
        self._model = None
        self._error: str | None = None
        self._lock = RLock()

    def load(self):
        with self._lock:
            if self._model is not None:
                return self._model
            if self._error:
                raise EmbeddingUnavailable(self._error)
            try:
                # Suppress library telemetry and incidental Hub metadata requests.
                # The one-time download runs in a separate CLI process.
                os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
                os.environ["HF_HUB_OFFLINE"] = "0" if self.allow_download else "1"
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    MODEL_NAME,
                    cache_folder=str(self.cache_dir),
                    device="cpu",
                    local_files_only=not self.allow_download,
                    trust_remote_code=False,
                )
                return self._model
            except Exception as exc:
                self._error = (
                    "Local MiniLM embeddings are unavailable. Run "
                    "`python -m grantiq.app.services.embeddings --download` once, then restart "
                    "GrantIQ. Keyword-only mission scoring is limited to 35% of its weight. "
                    f"Load failure: {type(exc).__name__}."
                )
                logger.warning("Local embedding load failed (%s)", type(exc).__name__)
                raise EmbeddingUnavailable(self._error) from exc

    @lru_cache(maxsize=2048)
    def _encode(self, text: str) -> tuple[float, ...]:
        with self._lock:
            vector = self.load().encode(
                text,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return tuple(float(value) for value in vector)

    def similarity(self, first: str, second: str) -> float:
        if not first.strip() or not second.strip():
            return 0.0
        try:
            a, b = self._encode(first), self._encode(second)
            similarity = sum(x * y for x, y in zip(a, b, strict=True))
            if not math.isfinite(similarity):
                raise ValueError("Embedding cosine similarity was not finite")
            return max(-1.0, min(1.0, similarity))
        except EmbeddingUnavailable:
            raise
        except Exception as exc:
            raise EmbeddingUnavailable(
                "Local embedding inference failed; keyword-only mission scoring is "
                f"limited to 35% of its weight ({type(exc).__name__})."
            ) from exc

    def status(self) -> dict:
        return {
            "model": MODEL_NAME,
            "cache_dir": str(self.cache_dir),
            "loaded": self._model is not None,
            "error": self._error,
            "downloads_allowed": self.allow_download,
        }


@lru_cache(maxsize=1)
def get_embedder() -> LocalEmbedder:
    return LocalEmbedder()


def main() -> None:
    from .. import config  # load .env and resolve the same cache as the server
    parser = argparse.ArgumentParser(description="Prepare or verify GrantIQ's free local MiniLM model")
    parser.add_argument("--download", action="store_true", help="Allow initial model download from Hugging Face")
    parser.add_argument("--cache-dir", default=None, help="Overrides GRANTIQ_MODEL_CACHE")
    args = parser.parse_args()
    embedder = LocalEmbedder(args.cache_dir, allow_download=args.download)
    try:
        score = embedder.similarity("Community eye health and vision care", "Preventing blindness with eye screenings")
    except EmbeddingUnavailable as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Ready: {MODEL_NAME}; cache={embedder.cache_dir}; sample cosine={score:.4f}")


if __name__ == "__main__":
    main()
