#!/usr/bin/env bash
# One-shot setup on Raspberry Pi OS (Bookworm or later), run as the normal user:
#   bash deploy/install-pi.sh
# Installs uv, the Python environment, serial permissions and the systemd service.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="live-plotter@${USER}.service"

echo "==> system packages (libcamera is not needed for USB webcams; OpenCV uses V4L2)"
sudo apt-get update
sudo apt-get install -y curl libgl1 libglib2.0-0 chromium

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

echo "==> dashboard kiosk on the attached display (starts with the desktop session)"
mkdir -p "$HOME/.config/autostart"
sed "s|%USER%|$USER|g" deploy/live-plotter-kiosk.desktop > "$HOME/.config/autostart/live-plotter-kiosk.desktop"
if command -v raspi-config >/dev/null 2>&1; then
  sudo raspi-config nonint do_blanking 1 || true   # keep the display on
  sudo raspi-config nonint do_boot_behaviour B4 || true   # boot to desktop, auto-login
fi

cat <<MSG

Done. Reboot (so the dialout group applies) and the piece starts by itself:
  sudo reboot
The dashboard appears full screen on the attached display, and is also at
  http://$(hostname).local:8080/  from any device on the same network.
Useful commands:
  systemctl status $SERVICE_NAME
  journalctl -u $SERVICE_NAME -f
  sudo systemctl stop $SERVICE_NAME     # lifts the pen and returns home
MSG
