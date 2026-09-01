ARG VERITAS_IMAGE=ghcr.io/chicagohai/veritas:latest
ARG VERITAS_PLATFORM=linux/amd64
FROM --platform=${VERITAS_PLATFORM} ${VERITAS_IMAGE}

USER root
WORKDIR /opt/medai
ARG MEDAI_PYPI_INDEX=https://pypi.org/simple

# Keep the common full-scale R analysis stack out of individual run directories.
# The exact versions match the first R/DuckDB replication environment; serial
# compilation prevents the amd64 Docker VM from exhausting memory on macOS.
RUN MAKEFLAGS=-j1 R --vanilla --slave -e '\
    options(repos = c(CRAN = "https://cloud.r-project.org")); \
    install <- function(package, version) { \
        remotes::install_version( \
            package, version = version, upgrade = "never", dependencies = NA \
        ); \
        if (utils::packageDescription(package, fields = "Version") != version) { \
            stop("Unexpected version for ", package); \
        } \
    }; \
    install("duckdb", "1.5.5"); \
    install("mice", "3.19.0"); \
    install("rms", "8.1-1"); \
    install("comorbidity", "1.1.0")'

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client sshpass \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY templates ./templates

RUN --mount=type=cache,target=/root/.cache/uv \
    UV_DEFAULT_INDEX="${MEDAI_PYPI_INDEX}" \
    UV_HTTP_TIMEOUT=120 UV_HTTP_RETRIES=5 UV_CONCURRENT_DOWNLOADS=4 \
    uv venv /opt/medai/.venv --python 3.12 \
    && uv pip install --python /opt/medai/.venv/bin/python --refresh-package medai "."

ENV PATH="/opt/medai/.venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/medai/.venv \
    PYTHONPATH=""

COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/medai-entrypoint

USER veritas
WORKDIR /workspace
ENTRYPOINT ["medai-entrypoint"]
