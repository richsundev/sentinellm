# syntax=docker/dockerfile:1
# python:3.12-slim, pinned by digest for reproducible builds — re-resolve
# with `docker pull python:3.12-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim`
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS builder
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install .

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS runtime
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
