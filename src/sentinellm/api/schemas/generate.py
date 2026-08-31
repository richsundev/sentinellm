from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sentinellm.api.schemas.trace import RetrievedDocumentIn


class GenerateRequest(BaseModel):
    application_id: str
    environment: str = "production"
    question: str
    system_prompt: str | None = None
    retrieved_documents: list[RetrievedDocumentIn] | None = None
    dataset_id: str | None = None
    top_k: int = 3
    preferred_model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    use_router: bool = True
    use_cache: bool = True
    prompt_id: str | None = None
    prompt_version: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluate: bool = True
