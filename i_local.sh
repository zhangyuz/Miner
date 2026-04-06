#!/bin/sh

set -x
set -e

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required (https://docs.astral.sh/uv/getting-started/installation/)"
    exit 1
fi

# POSIX path to repo root (works on macOS and Linux; avoids relying on realpath)
mydir=$(cd "$(dirname "$0")" && pwd)
cd "$mydir" || exit 1

if [ -f "/.dockerenv" ]; then
    echo "Running in docker"
    . "$HOME/venv/bin/activate"
    # Same six packages as before (minerservice stack — not MinerTrader/Maintainer)
    uv pip install --reinstall \
        "$mydir/Detonator" \
        "$mydir/DataMiner" \
        "$mydir/MarketBreadth" \
        "$mydir/MinerWorkers" \
        "$mydir/BrowserScraper" \
        "$mydir/MinerService"
else
    if [ -f "$HOME/venv/bin/activate" ]; then
        . "$HOME/venv/bin/activate"
        echo "Current Python Env: venv"
    elif command -v conda >/dev/null 2>&1; then
        CONDA_INSTALL_DIR=$(dirname $(dirname $(which conda)))
        . $CONDA_INSTALL_DIR/etc/profile.d/conda.sh
        conda activate miner
        echo "Current Python Env:" $CONDA_DEFAULT_ENV
    fi
    mkdir -pv $HOME/.miner
    cp $mydir/Deploy/miner/miner.json $HOME/.miner/

    if [ -n "$VIRTUAL_ENV" ]; then
        uv sync --active
    else
        uv sync
    fi
fi

set +x
set +e
