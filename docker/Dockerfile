ARG VERITAS_IMAGE=ghcr.io/chicagohai/veritas:latest
ARG VERITAS_PLATFORM=linux/amd64
FROM --platform=${VERITAS_PLATFORM} ${VERITAS_IMAGE}

USER root
WORKDIR /opt/medai
ARG MEDAI_PYPI_INDEX=https://pypi.org/simple

COPY pyproject.toml README.md ./
COPY src ./src
COPY templates ./templates

RUN --mount=type=cache,target=/root/.cache/uv \
    UV_DEFAULT_INDEX="${MEDAI_PYPI_INDEX}" \
    UV_HTTP_TIMEOUT=120 UV_HTTP_RETRIES=5 UV_CONCURRENT_DOWNLOADS=4 \
    uv venv /opt/medai/.venv --python 3.12 \
    && uv pip install --python /opt/medai/.venv/bin/python ".[pdf]" \
    && /opt/medai/.venv/bin/python -c \
        "import accelerate; import mineru.backend.hybrid.hybrid_analyze"

ENV PATH="/opt/medai/.venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/medai/.venv \
    PYTHONPATH=""

COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/medai-entrypoint

USER veritas
WORKDIR /workspace
ENTRYPOINT ["medai-entrypoint"]
