# Security

## API key authentication

Keys are high-entropy random tokens (`sk_sentinel_<32 random bytes,
url-safe base64>`, from `secrets.token_urlsafe`). Only a SHA-256 digest is
persisted (`api_keys.key_hash`, unique-indexed); the plaintext key is
returned exactly once, at creation
([`api/security.py`](../src/sentinellm/api/security.py)). SHA-256 (not
bcrypt/argon2) is the correct choice *here specifically* because these are
high-entropy generated tokens, not user-chosen passwords — there's no
brute-force-by-guessing risk a slow adaptive hash defends against, and a
fast hash is what lets every authenticated request do a single indexed
lookup instead of an expensive KDF on every call.

Every route except `/health` and the mock webhook receiver requires
`X-API-Key`; a missing or unrecognized key returns 401
([`api/deps.py`](../src/sentinellm/api/deps.py)).

## Role-based permissions

Three roles, `read < write < admin`
([`api/security.py`](../src/sentinellm/api/security.py) `ROLE_HIERARCHY`).
Every route declares its minimum required role via a FastAPI dependency
(`RequireRead`/`RequireWrite`/`RequireAdmin`); a key with insufficient
role gets 403. Application/API-key management is `admin`-only; ingestion
and generation are `write`; everything else is `read`.

## Environment separation

Every trace carries an `environment` field (`production`/`staging`/etc.),
filterable on every list endpoint and dashboard page — evaluations,
regressions, and cost figures from a staging deployment never silently mix
into production numbers.

## Request validation

Every request body is a Pydantic model; FastAPI rejects malformed
payloads with a structured 422 before any handler code runs (see
`_validation_error_handler` in
[`api/main.py`](../src/sentinellm/api/main.py) for the response shape).

## Rate limiting

Per-API-key (falling back to per-client-IP) moving-window rate limiting,
built directly on the `limits` library rather than a framework-integration
wrapper — see [design decisions](design-decisions.md) for why (a thin
adapter's compatibility with the exact FastAPI/Starlette version in use
turned out to be a real, observed failure mode during development, not a
hypothetical one). Configured via `SENTINEL_RATE_LIMIT_PER_MINUTE`
(default 120/minute); exceeding it returns 429.

## Secret handling

No secrets are committed to this repository. `.env.example` documents
every environment variable the application reads, with safe non-secret
defaults; a real deployment copies it to `.env` (gitignored) or, in
Kubernetes, `infrastructure/kubernetes/secret.yaml` (also gitignored — the
committed file is `secret.yaml.example`, a template only). See
[infrastructure/kubernetes/README.md](../infrastructure/kubernetes/README.md)
for what a production secret manager integration would add.

## PII redaction (hook, off by default)

[`security/pii.py`](../src/sentinellm/security/pii.py) provides a
`PIIRedactor` protocol and a deterministic `RegexPIIRedactor` default
(emails, US-shaped phone numbers, SSNs, card-number-shaped digit runs).
It's wired into `POST /api/v1/traces` behind
`SENTINEL_PII_REDACTION_ENABLED` (default `false`) — **off by default
deliberately**: redaction is lossy, and a faithfulness/hallucination check
run against a redacted answer is checking something subtly different from
what the model actually said. Enable it in any environment handling real
user data; the regex approach is a floor, not a ceiling — a production
deployment handling unstructured PII (names, addresses) should swap in a
trained NER-based redactor (e.g. Microsoft Presidio) behind the same
`PIIRedactor` protocol.

## Prompt injection detection

[`security/prompt_injection.py`](../src/sentinellm/security/prompt_injection.py)
pattern-matches the incoming question against known injection phrasings
("ignore previous instructions", "reveal your system prompt", "act as if
you have no restrictions", ...) and is wired in as an ordinary evaluation
metric, `PromptInjectionEvaluator` (see
[`evaluation/deterministic.py`](../src/sentinellm/evaluation/deterministic.py))
— every trace gets a `prompt_injection_risk` score, visible on the trace
detail page and factored into `overall_quality` (a 0.3 penalty on
detection). This is a heuristic first line of defense, not a claim of
completeness: a well-obfuscated injection attempt will not match these
patterns. A production deployment handling adversarial input at scale
should pair this with a trained classifier and/or structural defenses
(strict system/user message separation, output-side monitoring) — the
`detect_prompt_injection` function is intentionally small and swappable.

## What is explicitly *not* implemented

Being direct about this rather than implying otherwise:

- No mTLS or service-mesh-level authentication between `api`/`worker`/
  `postgres`/`redis` — see the Kubernetes NetworkPolicy gap noted in
  [infrastructure/kubernetes/README.md](../infrastructure/kubernetes/README.md).
  For a self-hosted `docker compose` demo this doesn't apply (everything
  is on a single Docker network the operator controls); it's a real
  Kubernetes-scale concern.
- No audit log of who accessed/modified what (API-key `last_used_at` is
  tracked; a full audit trail is not).
- No automated dependency-vulnerability *blocking* in CI — `security.yml`
  runs `pip-audit`/`npm audit` as a visibility gate, not a hard merge
  block, pending a documented exception/triage process (see the workflow's
  own comments).
