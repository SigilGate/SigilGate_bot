#!/bin/bash
set -e

# Настройка git-идентичности для коммитов в registry
git config --global user.name "Sigil Gate Bot"
git config --global user.email "bot@sigilgate.local"

# Настройка git-credentials для push в registry
if [ -n "${GITHUB_PAT:-}" ]; then
    git config --global credential.helper store
    echo "https://x-access-token:${GITHUB_PAT}@github.com" > ~/.git-credentials
    chmod 600 ~/.git-credentials
fi

exec python -m bot
