FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        nodejs \
        npm \
        openssh-client \
        rsync \
        sshpass \
    && npm install -g @anthropic-ai/claude-code @openai/codex \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/medai
COPY pyproject.toml README.md ./
COPY src ./src
COPY templates ./templates
RUN pip install ".[pdf]"

COPY docker/entrypoint.sh /usr/local/bin/medai-entrypoint
RUN chmod +x /usr/local/bin/medai-entrypoint

ENTRYPOINT ["medai-entrypoint"]
