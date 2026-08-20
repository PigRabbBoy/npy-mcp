FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace root + all packages (needed for uv workspace resolution)
COPY pyproject.toml ./
COPY packages/ ./packages/

# Build all wheels
RUN uv build --all-packages

# ---- runtime stage ----
FROM python:3.12-slim

WORKDIR /app

# Copy built wheels from builder
COPY --from=builder /build/dist/ /wheels/

# Install npy-mcp + its deps (npy-core pulled automatically)
RUN pip install --no-cache-dir npy-mcp --find-links /wheels/

# Clean up wheels to keep image small
RUN rm -rf /wheels

# Default to HTTP transport for remote deployment
# Override with: docker run ... notion-mcp --transport stdio
EXPOSE 8000

# Default env (override at runtime)
ENV NOTION_MCP_HOST=0.0.0.0
ENV NOTION_MCP_PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/mcp', timeout=3)" || exit 1

ENTRYPOINT ["notion-mcp", "--transport", "http"]
CMD ["--host", "0.0.0.0", "--port", "8000"]