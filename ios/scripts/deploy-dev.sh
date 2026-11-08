#!/bin/bash
# Builds the Debug app (development signing, sandbox APNs), installs it on the phone over Wi-Fi or USB, and
# launches it. The phone must be paired with this Mac and have Developer Mode on.
#
#   ios/scripts/deploy-dev.sh            # the phone named LXEPhone17Pro
#   DEVICE="Other iPhone" ios/scripts/deploy-dev.sh
#
# Signing is automatic. With ~/.config/phoneuse/asc.env (ASC_KEY_ID, ASC_ISSUER_ID and ASC_KEY_PATH, an App Store
# Connect API key), xcodebuild creates or updates the development profiles itself; without it, it uses the Apple ID
# signed in to Xcode.
set -euo pipefail
cd "$(dirname "$0")/.."

DEVICE="${DEVICE:-LXEPhone17Pro}"
BUNDLE_ID=co.lxe.phoneuse
DERIVED=build/dev

udid=$(xcrun devicectl list devices --json-output /dev/stdout 2>/dev/null | python3 -c '
import json, sys
name = sys.argv[1]
for d in json.load(sys.stdin)["result"]["devices"]:
    if name in (d["deviceProperties"].get("name"), d["hardwareProperties"].get("udid"), d.get("identifier")):
        print(d["hardwareProperties"]["udid"]); break
' "$DEVICE" || true)
if [ -z "$udid" ]; then
    echo "No paired device named $DEVICE. Pair it in Xcode (Window > Devices and Simulators) first." >&2
    exit 1
fi

auth=()
if [ -f ~/.config/phoneuse/asc.env ]; then
    # shellcheck disable=SC1090
    source ~/.config/phoneuse/asc.env
    auth=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID"
          -authenticationKeyIssuerID "$ASC_ISSUER_ID")
fi

echo "Building for $DEVICE ($udid)…"
xcodebuild build -project PhoneUse.xcodeproj -scheme PhoneUse -configuration Debug \
    -destination "id=$udid" -derivedDataPath "$DERIVED" \
    -allowProvisioningUpdates -allowProvisioningDeviceRegistration "${auth[@]}" -quiet

app="$DERIVED/Build/Products/Debug-iphoneos/PhoneUse.app"
echo "Installing…"
xcrun devicectl device install app --device "$udid" "$app" >/dev/null
echo "Launching…"
xcrun devicectl device process launch --device "$udid" --terminate-existing "$BUNDLE_ID" >/dev/null
echo "Installed and launched $(git rev-parse --short HEAD)$(git diff --quiet HEAD -- . || echo '+changes') on $DEVICE."
