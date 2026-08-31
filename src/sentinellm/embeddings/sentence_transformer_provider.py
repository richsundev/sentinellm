"""Optional production embedding provider backed by `sentence-transformers`.

Not imported anywhere by default — importing this module requires the
`sentence-transformers` extra to be installed, which is deliberately kept out
of the base dependency set so the platform's default install stays light and
offline-friendly. Wire it in via `SENTINEL_EMBEDDING_PROVIDER=sentence-transformers`.
"""

from __future__ import annotations

from sentinellm.embeddings.base import EmbeddingProvider


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    name = "sentence-transformers"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Install it with `pip install sentence-transformers` to use this provider."
            ) from exc
        self._model = SentenceTransformer(model_name)
        self.dimensions = self._model.get_sentence_embedding_dimension()

    async def embed(self, text: str) -> list[float]:
        import asyncio

        return await asyncio.to_thread(lambda: self._model.encode(text).tolist())
