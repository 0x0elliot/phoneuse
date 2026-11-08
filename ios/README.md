# PhoneUse companion app

The iOS app described in [docs/COMPANION.md](../docs/COMPANION.md).

- `xcodegen generate` regenerates `PhoneUse.xcodeproj` from `project.yml`.
- Debug builds sign automatically. Release builds sign manually with the "PhoneUse AppStore" and
  "PhoneUse Widgets AppStore" profiles (Apple Distribution, team 9592R2Q8PP).
- Tests: start `mock/mock_server.py` (see `UITests/SettingsUITests.swift` for the arguments), then
  `xcodebuild test -scheme PhoneUse -destination 'platform=iOS Simulator,name=iPhone 17 Pro'`.
- The app group `group.co.lxe.phoneuse` is optional. To add it, create it in the developer portal, enable App
  Groups on both App IDs with it, regenerate the profiles, and put `com.apple.security.application-groups`
  back in `project.yml` for both targets. The app moves the pairing into the group by itself.
