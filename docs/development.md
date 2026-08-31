# Development guide

## Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Node 20+
- Docker + Docker Compose (for Postgres/Redis, or the full stack)

## Backend setup

```bash
make install                          # uv venv .venv + editable install with dev deps
docker compose up -d postgres redis   # just the stateful dependencies
make migrate                          # alembic upgrade head
make seed                             # populate demo data (idempotent)
make dev-api                          # uvicorn --reload on :8000
```

In a second terminal, if you want the worker running too (only needed to
process traces created *after* seeding — the seed script evaluates
synchronously):

```bash
make dev-worker
```

Environment variables: copy `.env.example` to `.env` and adjust. Every
variable the application reads is documented there — this is the single
source of truth for configuration, not scattered magic numbers in code
(see [`core/config.py`](../src/sentinellm/core/config.py)).

## Frontend setup

```bash
make frontend-install
make frontend-dev     # :3000, talks to :8000 by default (NEXT_PUBLIC_API_URL)
```

## Running tests

```bash
make test              # backend: pytest, zero external services required
make frontend-test      # frontend: jest + react-testing-library
make validate           # everything CI runs, in one command
```

The backend suite runs entirely against SQLite + `MockProvider` +
`MockEmbeddingProvider` — no Postgres, Redis, or real LLM API key needed.
If a test needs a populated database, it uses the `db_session`/`engine`
fixtures in [`tests/conftest.py`](../tests/conftest.py) (a fresh in-memory
SQLite database per test, via `StaticPool` so the whole test shares one
connection).

## Linting and type checking

```bash
make lint     # ruff check + mypy
make format   # ruff format + ruff check --fix
```

CI (`lint.yml`) runs `ruff check`, `ruff format --check` (so an unformatted
diff fails the build — always run `make format` before committing), and
`mypy` with a strict-ish config (see `[tool.mypy]` in `pyproject.toml`).

## Database migrations

```bash
# after changing a model in src/sentinellm/db/models.py:
.venv/bin/alembic revision --autogenerate -m "describe the change"
# review the generated file in src/sentinellm/db/migrations/versions/ before committing —
# autogenerate is a starting point, not a guarantee (index/constraint renames
# in particular often need a manual nudge)
.venv/bin/alembic upgrade head
```

Migrations are generated against SQLite during development (fast, no
Postgres required) but are also verified against real PostgreSQL by the
`build.yml` CI workflow's full `docker compose up` smoke test — this
matters: a bug that only Postgres enforces (e.g. a `VARCHAR` length limit
SQLite silently ignores) will not show up in the SQLite-based unit tests.
This happened once during this project's own development — the `api_keys.
key_prefix` column was originally sized for the demo key's length, not a
real generated key's, and only Postgres's strict `VARCHAR(n)` enforcement
caught it.

## Reproducing the demo data

```bash
.venv/bin/python scripts/seed_demo.py           # idempotent — no-ops if already seeded
.venv/bin/python scripts/seed_demo.py --force    # reseed from scratch
```

Read [`scripts/seed_demo.py`](../scripts/seed_demo.py) top to bottom for
exactly how the regression/routing/caching demo scenarios are constructed
— every number it produces comes from actually running the router,
resilient client, semantic cache, and evaluation pipeline, not from
fixture data.

## Reproducing the benchmark numbers in the README/docs/performance.md

```bash
make bench                                    # or:
.venv/bin/python scripts/run_benchmarks.py --iterations 200 --output results.json
```

## Project conventions

- **No comments explaining *what* code does** — names should do that.
  Comments explain *why* when it's non-obvious (a workaround, an invariant,
  a past incident). Grep the codebase for examples of the style being
  aimed for before adding new comments.
- **Domain-oriented modules, not purely technical layers** — see
  [docs/architecture.md](architecture.md) and [design decision
  11](design-decisions.md#11-a-modular-monolith-not-eight-physical-microservices).
- **Every evaluator/provider is behind a small interface** (`Evaluator`,
  `LLMProvider`, `EmbeddingProvider`, `ClaimExtractor`/`ClaimVerifier`,
  `ModelStatsProvider`, `PIIRedactor`) — new implementations are additive,
  never require touching call sites.
- **New DB columns/tables always go through Alembic** — never hand-edit
  the schema; `init_models()` (`create_all`) exists only for tests and the
  demo seed script's convenience, not as a migration substitute.
