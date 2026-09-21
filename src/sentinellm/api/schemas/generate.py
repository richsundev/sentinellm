from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import Field, StringConstraints, model_validator

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
    # When set (even to `{}`), `prompt_id` is *served*: the template of
    # `prompt_version` (default: the newest production version) is rendered with
    # these values — plus `question` and `context`, filled in from the request
    # unless overridden here — and sent as the system prompt. Left unset,
    # `prompt_id`/`prompt_version` are only recorded on the trace.
    prompt_variables: dict[str, str] | None = Field(default=None, max_length=50)
    prompt_version: int | None = Field(default=None, ge=1, le=2_147_483_647)
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluate: bool = True

    @model_validator(mode="after")
    def _prompt_variables_need_a_prompt(self) -> GenerateRequest:
        if self.prompt_variables is None:
            return self
        if not self.prompt_id:
            raise ValueError("prompt_variables requires prompt_id")
        for name in self.prompt_variables:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,49}", name):
                raise ValueError(f"invalid prompt variable name: {name!r}")
        return self
