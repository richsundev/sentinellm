# syntax=docker/dockerfile:1
# python:3.12-slim, pinned by digest for reproducible builds — re-resolve
# with `docker pull python:3.12-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim`
FROM python:3.14-slim@sha256:656d12e70054d5fda18a045e2494c96701e9792dd1445f95b3d038df954f57e9 AS builder
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install .

FROM python:3.14-slim@sha256:656d12e70054d5fda18a045e2494c96701e9792dd1445f95b3d038df954f57e9 AS runtime
WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system sentinel && useradd --system --gid sentinel --create-home sentinel

COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY datasets ./datasets

RUN chown -R sentinel:sentinel /app
USER sentinel

CMD ["python", "-m", "sentinellm.worker.main"]
