#!/usr/bin/env bash
# Change the sheet of paper without the dashboard: stop the piece, forget what was
# drawn, start it again (it then waits for the start button on the dashboard).
# Run on the Raspberry Pi:  bash deploy/new-paper.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="live-plotter@${USER}.service"

echo "==> stopping (the pen lifts and returns home)"
sudo systemctl stop "$SERVICE_NAME"
echo "==> forgetting the previous sheet"
rm -rf "$PROJECT_DIR/state"
read -r -p "Put the new sheet in place with the pen at the top-left corner, then press Enter: " _
echo "==> starting"
sudo systemctl start "$SERVICE_NAME"
echo "Restarted. Press 開始 on the dashboard to draw. Log: journalctl -u $SERVICE_NAME -f"
