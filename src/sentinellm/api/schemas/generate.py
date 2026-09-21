from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sentinellm.api.schemas.trace import RetrievedDocumentIn

_USE_ROUTER_DEPRECATION = (
    "Has no effect. Model selection is: `preferred_model` if set; otherwise the "
    "application's canary rollout split, if one exists; otherwise the router. "
    "Set `preferred_model` to bypass routing."
)


class GenerateRequest(BaseModel):
    application_id: str
    environment: str = "production"
    question: str = Field(min_length=1)
    system_prompt: str | None = None
    retrieved_documents: list[RetrievedDocumentIn] | None = None
    dataset_id: str | None = None
    top_k: int = Field(default=3, ge=1, le=50)
    preferred_model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    use_router: bool = Field(
        default=True,
        description=_USE_ROUTER_DEPRECATION,
        deprecated=_USE_ROUTER_DEPRECATION,
    )
    use_cache: bool = True
    prompt_id: str | None = None
    prompt_version: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluate: bool = True
