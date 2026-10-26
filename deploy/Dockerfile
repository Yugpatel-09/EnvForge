FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
RUN uv pip install --system 'uv>=0.11.1,<0.12'
WORKDIR /opt/envforge
COPY . .
RUN uv build --wheel --out-dir /tmp/wheels && uv pip install --system --no-sources /tmp/wheels/*.whl ./apps/api \
    && useradd --uid 10001 --create-home envforge && mkdir /data && chown envforge /data
USER envforge
ENV ENVFORGE_DB_PATH=/data/envforge.sqlite3
ENV UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
