#!/usr/bin/env bash
# One-shot setup on Raspberry Pi OS (Bookworm or later), run as the normal user:
#   bash deploy/install-pi.sh
# Installs uv, the Python environment, serial permissions and the systemd service.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="live-plotter@${USER}.service"

echo "==> system packages (libcamera is not needed for USB webcams; OpenCV uses V4L2)"
sudo apt-get update
sudo apt-get install -y curl libgl1 libglib2.0-0

if ! command -v uv >/dev/null 2>&1; then
  echo "==> installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> python environment (includes the AxiDraw API)"
cd "$PROJECT_DIR"
uv sync --extra axidraw

echo "==> serial port permission for the AxiDraw"
sudo usermod -aG dialout "$USER"

echo "==> systemd service: $SERVICE_NAME"
sudo cp deploy/live-plotter.service /etc/systemd/system/live-plotter@.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

cat <<MSG

Done. Reboot (so the dialout group applies) and the piece starts by itself:
  sudo reboot
Useful commands:
  systemctl status $SERVICE_NAME
  journalctl -u $SERVICE_NAME -f
  sudo systemctl stop $SERVICE_NAME     # lifts the pen and returns home
MSG
