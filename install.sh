#!/bin/sh
# Make this PC look like a Bluetooth mouse+keyboard and run hidd as a service.
# Undo: sudo ./install.sh --uninstall
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
OVR=/etc/systemd/system/bluetooth.service.d/iphone-hid.conf
CONF=/etc/bluetooth/main.conf

if [ "$1" = "--uninstall" ]; then
  systemctl disable --now iphone-hid.service 2>/dev/null || true
  rm -f /etc/systemd/system/iphone-hid.service "$OVR"
  sed -i '/^# iphone-hid$/{N;d}' "$CONF"
  systemctl daemon-reload
  systemctl restart bluetooth
  exit 0
fi

# 1. bluetoothd without the input plugin (hidd owns HID PSMs 17/19) and without the
#    hostname plugin (it resets the device class to "desktop computer").
mkdir -p "$(dirname "$OVR")"
cat > "$OVR" <<EOF
[Service]
ExecStart=
ExecStart=/usr/lib/bluetooth/bluetoothd --noplugin=input,hostname
EOF

# 2. Device class: peripheral, keyboard+pointing combo. iOS lists the PC as an input device.
grep -q '^# iphone-hid$' "$CONF" || sed -i '/^\[General\]/a # iphone-hid\nClass = 0x0025C0' "$CONF"

# 3. hidd service. Command socket is group-writable for wheel.
cat > /etc/systemd/system/iphone-hid.service <<EOF
[Unit]
Description=Bluetooth HID mouse+keyboard for an iPhone
After=bluetooth.service
Requires=bluetooth.service
PartOf=bluetooth.service

[Service]
Environment=HID_GID=$(getent group wheel | cut -d: -f3)
ExecStart=/usr/bin/python -u $DIR/hidd.py
Restart=on-failure

[Install]
WantedBy=bluetooth.target
EOF

systemctl daemon-reload
systemctl restart bluetooth
systemctl reset-failed iphone-hid.service 2>/dev/null || true
systemctl enable --now iphone-hid.service
