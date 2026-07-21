FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

ARG UV_GROUPS=""

COPY pyproject.toml uv.lock README.md ./
RUN if [ -n "$UV_GROUPS" ]; then \
      uv sync --frozen --no-default-groups --no-install-project --group "$UV_GROUPS"; \
    else \
      uv sync --frozen --no-default-groups --no-install-project; \
    fi

COPY src ./src
RUN if [ -n "$UV_GROUPS" ]; then \
      uv sync --frozen --no-default-groups --group "$UV_GROUPS"; \
    else \
      uv sync --frozen --no-default-groups; \
    fi

CMD ["uv", "run", "--no-sync", "pit", "doctor"]
