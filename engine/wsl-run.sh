#!/bin/bash
# Launcher do motor swengine dentro do WSL/Ubuntu (ambiente ~/.swengine-env).
# Uso: wsl -d Ubuntu -- bash engine/wsl-run.sh <comando-cli> [--json arq]
# As libs de sistema extraídas sem sudo ficam em ~/.swengine-libs.
export LD_LIBRARY_PATH="$HOME/.swengine-libs/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
export MPLBACKEND=Agg
cd "$(dirname "$0")"
exec "$HOME/.swengine-env/bin/python" -m swengine "$@"
