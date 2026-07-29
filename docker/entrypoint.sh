#!/usr/bin/env bash
set -euo pipefail

runtime_home="$(mktemp -d /tmp/medai-home.XXXXXX)"
trap 'rm -rf "$runtime_home"' EXIT

if [[ -d /credentials/codex ]]; then
    cp -a /credentials/codex "$runtime_home/.codex"
fi
if [[ -d /credentials/claude ]]; then
    cp -a /credentials/claude "$runtime_home/.claude"
fi
if [[ -d /credentials/ssh ]]; then
    cp -a /credentials/ssh "$runtime_home/.ssh"
    chmod -R go-rwx "$runtime_home/.ssh"
fi

export HOME="$runtime_home"
export CODEX_HOME="$runtime_home/.codex"
export CLAUDE_CONFIG_DIR="$runtime_home/.claude"
export MEDAI_TEMPLATES_DIR=/opt/medai/templates
export MEDAI_SKILLS_DIR=/opt/medai/templates/skills

exec python -m medai.cli "$@"
