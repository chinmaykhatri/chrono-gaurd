FROM ghcr.io/astral-sh/uv:0.11.26@sha256:3d868e555f8f1dbc324afa005066cd11e1053fc4743b9808ca8025283e65efa5 AS uv
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY verifier/pyproject.toml verifier/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY verifier/app ./app
COPY verifier/migrations ./migrations
COPY verifier/alembic.ini ./
COPY eval/dataset /eval/dataset
RUN useradd --system --uid 10001 --no-create-home verifier
USER 10001
EXPOSE 8088
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088", "--no-access-log"]
