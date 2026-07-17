FROM europe-north1-docker.pkg.dev/cgr-nav/pull-through/nav.no/python:3.13-dev AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv@sha256:87a04222b228501907f487b338ca6fc1514a93369bfce6930eb06c8d576e58a4 \
     /uv /usr/local/bin/uv

# tell uv exactly where to put the venv and don't let it roam
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev \
 && /app/.venv/bin/uvicorn --version

FROM europe-north1-docker.pkg.dev/cgr-nav/pull-through/nav.no/python:3.13-dev AS runner

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

COPY --chown=1069:1069 --from=builder /app/.venv /app/.venv
COPY --chown=1069:1069 summarize_costs.py map_teams.py enrich_seksjon.py visualize.py main.py ./

USER 1069
EXPOSE 8080
ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]