from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StringConstraints

from sentinellm.api.schemas.common import NulStrippingModel
from sentinellm.api.schemas.trace import RetrievedDocumentIn

_USE_ROUTER_DEPRECATION = (
    "Has no effect. Model selection is: `preferred_model` if set; otherwise the "
    "application's canary rollout split, if one exists; otherwise the router. "
    "Set `preferred_model` to bypass routing."
)


class GenerateRequest(NulStrippingModel):
    application_id: str = Field(min_length=1, max_length=200)
    environment: str = Field(default="production", min_length=1, max_length=50)
    question: str = Field(min_length=1)
    system_prompt: str | None = None
    retrieved_documents: list[RetrievedDocumentIn] | None = None
    dataset_id: str | None = Field(default=None, max_length=36)
    top_k: int = Field(default=3, ge=1, le=50)
    preferred_model: str | None = Field(default=None, max_length=100)
    fallback_models: list[Annotated[str, StringConstraints(max_length=100)]] = Field(
        default_factory=list, max_length=10
    )
    use_router: bool = Field(
        default=True,
        description=_USE_ROUTER_DEPRECATION,
        deprecated=_USE_ROUTER_DEPRECATION,
    )
    use_cache: bool = True
    prompt_id: str | None = Field(default=None, max_length=200)
    prompt_version: int | None = Field(default=None, ge=1, le=2_147_483_647)
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluate: bool = True
