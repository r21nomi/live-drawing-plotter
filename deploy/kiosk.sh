#!/usr/bin/env bash
# Show the dashboard full screen on the display attached to the Raspberry Pi.
# Started automatically at desktop login (see install-pi.sh); can also be run by hand.
set -u

URL="${LIVE_PLOTTER_URL:-http://localhost:8080/}"

# Wait until the piece is serving its dashboard (it may still be connecting to the camera).
for _ in $(seq 1 120); do
  if curl -fs -o /dev/null "$URL"; then break; fi
  sleep 1
done

if command -v chromium >/dev/null 2>&1; then BROWSER=chromium
elif command -v chromium-browser >/dev/null 2>&1; then BROWSER=chromium-browser
else echo "chromium is not installed (sudo apt-get install chromium)" >&2; exit 1
fi

exec "$BROWSER" \
  --kiosk "$URL" \
  --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --disable-features=TranslateUI --check-for-update-interval=31536000 \
  --incognito --no-first-run --start-fullscreen --hide-scrollbars
