# Phone Use companion app

The iOS app and Live Activity described in [docs/COMPANION.md](../docs/COMPANION.md). SwiftUI, iOS 17.2+.

## Layout

- `App/`: the app (pairing, the settings screen, push tokens, notification actions).
- `Widgets/`: the Live Activity and Dynamic Island views.
- `Shared/`: code both targets use: request signing and sealing (`CompanionCrypto`), the client, the pairing
  (Keychain), the activity's attributes and intents, and the driving robot (`Robot.swift`).
- `mock/`: a Python mock of the PC's API for tests, with fixed crypto vectors.
- `scripts/`: the deploy script and design tools.

`project.yml` is the source of truth for the Xcode project. Run `xcodegen generate` after changing it or adding
files; `PhoneUse.xcodeproj` is committed.

## Build and install on the phone

```
ios/scripts/deploy-dev.sh                      # the phone named LXEPhone17Pro
DEVICE="Other iPhone" ios/scripts/deploy-dev.sh
```

It builds the Debug configuration, installs it with `devicectl` over Wi-Fi or USB and launches it, in about
30 seconds. The phone must be paired with this Mac (Xcode, Devices and Simulators) with Developer Mode on.
A Debug build uses the sandbox APNs environment and registers with the PC as `"env": "sandbox"`.

## Signing

- Debug signs automatically. With `~/.config/phoneuse/asc.env` (outside the repo: `ASC_KEY_ID`,
  `ASC_ISSUER_ID`, `ASC_KEY_PATH` for an App Store Connect API key), `deploy-dev.sh` lets xcodebuild create and
  update the development profiles itself; without it, xcodebuild uses the Apple ID signed in to Xcode.
- Release signs manually with the "PhoneUse AppStore" and "PhoneUse Widgets AppStore" profiles (Apple
  Distribution, team 9592R2Q8PP), for TestFlight. Those profiles predate the time-sensitive notification
  entitlement; regenerate them before the next upload.
- A TestFlight (production) install and a development install get different push tokens, and iOS can keep
  handing a reinstalled build the old push-to-start token. Deleting the app and installing again fixes that;
  the pairing survives, because it's also kept in the Keychain.

## Tests

Start the mock with the fixed test key, then run the tests:

```
python3 -m venv ios/mock/.venv && ios/mock/.venv/bin/pip install cryptography
ios/mock/.venv/bin/python ios/mock/mock_server.py --key AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8 --cursor-delay 1
xcodebuild test -project ios/PhoneUse.xcodeproj -scheme PhoneUse \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -skip-testing:PhoneUseUITests/RealPCUITests -skip-testing:PhoneUseUITests/LiveActivityLayoutUITests
```

- `Tests/`: signing and sealing against the mock's vectors (`mock/vectors.py`), pairing links, and decoding.
- `UITests/SettingsUITests`: pairs with the mock from a link and drives every setting. The mock logs one JSON
  line per request, with the unsealed secrets' lengths, so the log shows what the app sent.
- `UITests/RealPCUITests`: read-only pairing with a real PC; run it with `TEST_RUNNER_PU_LINK=<pairing link>`.
- `mock/mock_server.py --help` lists its options (`--agent idle` starts with no agent, `--bonjour` advertises it).

## The Live Activity

One activity stays up while the phone mirrors to the PC; the PC drives it with pushes. It shows one card per
state (idle, asking, driving, paused). While driving, the PC refreshes it every second at priority 10 with
`frame` counting up: the ring turns 45 degrees per frame, and the robot plays an 8-step loop per phase. Timer-driven
views don't move in the compact Dynamic Island, and priority-5 refreshes get held back, so both are needed.
While Screen Mirroring's own activity shares the island, iOS shows only our compact leading view.

The app logs the tokens it gets and sends to `Library/Caches/phoneuse.log`:

```
xcrun devicectl device copy from --device <udid> --domain-type appDataContainer \
  --domain-identifier co.lxe.phoneuse --source Library/Caches/phoneuse.log --destination phoneuse.log
```

## Design tools

- Launch a Debug build with `-PUDemo idle|warning|delay|asking|driving|paused` to show one Live Activity in that state
  with no PC. `UITests/LiveActivityLayoutUITests` uses it to capture each state on the simulator's lock screen.
- `scripts/robot_preview.swift` renders the robot's loops frame by frame with the real view, eased as iOS
  animates them (build instructions at the top of the file).
- `scripts/app_icon_candidates.swift` renders app icon candidates with their dark and tinted variants and a
  preview sheet. `mock/make_icon.py` draws the current icon.
- The app group `group.co.lxe.phoneuse` is optional. To add it, create it in the developer portal, enable App
  Groups on both App IDs, regenerate the profiles, and add `com.apple.security.application-groups` to both
  targets in `project.yml`. The app moves the pairing into the group by itself.
