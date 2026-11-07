#!/bin/sh
# airwisp Bluetooth side: make this PC look like a mouse + keyboard to the iPhone,
# and run the HID daemon as a system service. Run with sudo (or via `airwisp install`).
#   sudo scripts/install.sh              install / update
#   sudo scripts/install.sh --uninstall  remove everything this installs
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OVR=/etc/systemd/system/bluetooth.service.d/airwisp.conf
CONF=/etc/bluetooth/main.conf
UNIT=/etc/systemd/system/airwisp-hid.service
USER_NAME=${SUDO_USER:-$(logname 2>/dev/null || echo root)}

# Older checkouts installed this as "iphone-hid"; replace it.
if [ -f /etc/systemd/system/iphone-hid.service ]; then
  systemctl disable --now iphone-hid.service 2>/dev/null || true
  rm -f /etc/systemd/system/iphone-hid.service /etc/systemd/system/bluetooth.service.d/iphone-hid.conf
  sed -i '/^# iphone-hid$/{N;d}' "$CONF"
fi

if [ "$1" = "--uninstall" ]; then
  systemctl disable --now airwisp-hid.service 2>/dev/null || true
  rm -f "$UNIT" "$OVR"
  sed -i '/^# airwisp$/{N;d}' "$CONF"
  systemctl daemon-reload
  systemctl restart bluetooth
  echo "removed (the allow list in /etc/airwisp/ is kept)"
  exit 0
fi

# Device name from the user's config (default "airwisp").
NAME=$(su "$USER_NAME" -c "cd '$ROOT' && python3 -c 'from airwisp.config import NAME; print(NAME)'" 2>/dev/null || echo airwisp)

# 1. bluetoothd without the input plugin (the daemon owns HID PSMs 17/19) and
#    without the hostname plugin (it resets the device class to "computer").
mkdir -p "$(dirname "$OVR")"
cat > "$OVR" <<EOC
[Service]
ExecStart=
ExecStart=/usr/lib/bluetooth/bluetoothd --noplugin=input,hostname
EOC

# 2. Device class: peripheral, keyboard + pointing device.
grep -q '^# airwisp$' "$CONF" || sed -i '/^\[General\]/a # airwisp\nClass = 0x0025C0' "$CONF"

# 3. Allow list: empty means "trust the first device that pairs".
mkdir -p /etc/airwisp
touch /etc/airwisp/allowed

# 4. The daemon. Its command socket is writable by the "wheel" group.
GID=$(getent group wheel | cut -d: -f3)
cat > "$UNIT" <<EOC
[Unit]
Description=airwisp: Bluetooth mouse + keyboard for an iPhone
After=bluetooth.service
Requires=bluetooth.service
PartOf=bluetooth.service

[Service]
Environment=AIRWISP_NAME=$NAME
Environment=HID_GID=${GID:-0}
WorkingDirectory=$ROOT
ExecStart=/usr/bin/python3 -u -m airwisp.hid_daemon
Restart=on-failure

[Install]
WantedBy=bluetooth.target
EOC

systemctl daemon-reload
systemctl restart bluetooth
systemctl reset-failed airwisp-hid.service 2>/dev/null || true
systemctl enable --now airwisp-hid.service
echo "airwisp-hid running as '$NAME'. On the iPhone: Settings > Bluetooth > $NAME"
