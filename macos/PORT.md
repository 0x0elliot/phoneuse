# phoneuse on macOS

A macOS port of phoneuse: the same CLI an agent uses, driving an unmodified
iPhone from a MacBook. Nothing runs on the phone.

This is **not** a literal port. The Linux version talks to the phone over two
channels: AirPlay video in, Bluetooth HID out. macOS cannot be a Bluetooth HID
peripheral, and it already has a better version of both channels built in: its
own iPhone Mirroring window. So the transport is swapped, and the command
surface is kept.

## What changed

| Job | Linux | macOS |
|---|---|---|
| Screen in | UxPlay AirPlay receiver → hub → GTK4 window | the iPhone Mirroring window (ScreenCaptureKit, via `screencapture -l`) |
| Input out | Bluetooth HID mouse + keyboard via a root daemon | synthetic `CGEvent` clicks and keystrokes into that window |
| Mirror the user watches | browser mirror at `:8777` | the iPhone Mirroring window itself |
| OCR | local model service over HTTP | Vision framework, in-process |
| Window/compositor glue | Hyprland IPC + `/dev/input` | AppKit + Accessibility permission |
| Pairing | Bluetooth "Just Works" | Apple ID, handled by the OS |
| Root service | `phoneuse-hid` systemd unit | none — no `sudo` anywhere |

That last row is the nice part: there is no daemon, no root, no Bluetooth
pairing, no ESP32 bridge, and no `bluetoothd` surgery. The cost is that
everything now depends on Apple's mirroring session, which has its own rules
(see Limits).

## Install

```bash
cd macos
./install.sh          # builds release, links ~/.local/bin/phoneuse-mac
```

Then:

1. Open **iPhone Mirroring** (`/System/Applications/iPhone Mirroring.app`),
   sign in with the same Apple ID as the phone, and pair.
2. On the phone, keep it locked and idle: that is the state mirroring needs.
3. Give **Screen Recording** and **Accessibility** to the terminal you run
   commands from (System Settings › Privacy & Security), then restart that
   terminal.
4. `phoneuse-mac status` should print `ready: yes`.

## Commands

Same names and coordinate convention as the Linux CLI: fractions of the phone
screen, 0 to 1, origin top-left. Any action ends with `--text` to read the
screen afterwards.

```bash
phoneuse-mac status
phoneuse-mac text                      # "x y  text" lines, OCR'd locally
phoneuse-mac tap-on "Wi-Fi"            # tap the matching line
phoneuse-mac tap 0.5 0.35 --text
phoneuse-mac type "hello"              # replaces the field; --append keeps it
phoneuse-mac key enter
phoneuse-mac scroll down
phoneuse-mac swipe 0.5 0.8 0.5 0.2
phoneuse-mac open "Settings"           # Home, then tap the icon's label
phoneuse-mac screenshot shot.png
phoneuse-mac done                      # hands the window back to the user
```

`PHONEUSE_MAC_HOME_COMBO` overrides the Home shortcut (default `cmd+shift+h`,
matching the iPhone Mirroring menu). `PHONEUSE_MAC_CROP_TOP` overrides the
title-bar crop in points if the automatic detection gets it wrong.

## What the port does not have yet

- **No MCP server.** The Linux repo exposes `look`, `tap`, `tap_on`, `wait`,
  `unlock` and friends over MCP. This is CLI only; the MCP wrapper is the next
  obvious step (`scripts/setup-mcp.sh` equivalent).
- **No settle/frames logic.** Linux waits for the screen to stop changing and
  returns three frames (0.1/0.4/0.8 s) so an agent can judge motion. Here
  `--text` just sleeps 0.8 s and reads once. Porting `frames.py` is the single
  biggest quality gap.
- **No unlock.** Not needed: iPhone Mirroring keeps the phone locked and gives
  you the session anyway. Anything that demands Face ID or a passcode *inside*
  an app will pop on the phone itself and stall the loop.
- **No `longpress` timing calibration, no `cursor`/AssistiveTouch, no
  notifications-read, no bridge, no `awake`.** `longpress` exists but uses a
  fixed hold.
- **No app switcher, no Control Center gesture.** `back` is an edge swipe,
  `home` is a keystroke; the rest need real gestures.

## Limits worth knowing before you build on it

- **The phone's own screen is off while mirroring.** Good for privacy, bad for
  filming: the only picture is the Mac window.
- **Secure surfaces go blank.** Banking apps and anything with
  `UIScreen.isCaptured` protection can render black in the captured window.
  Do not promise a demo on a banking app until you have tried that app.
- **One Apple ID, one phone, one window.** Two paired phones means picking the
  window by size, not by name.
- **Clicks are synthetic.** Some apps notice; the OS will refuse them entirely
  without Accessibility permission.
- **Latency is Apple's, not the port's.** Roughly a frame or two, and much
  better than the Linux path's ~100 ms AirPlay round trip.

## Why this exists

`lxe/phoneuse` open-sources the idea (MIT) but only for Linux, and `macOS
support` is an open issue on the upstream repo. This directory is that port,
scoped to the part that actually matters: an agent can look at the phone screen
as text and act on it, with no root, no jailbreak, no app on the phone, and no
extra hardware.
