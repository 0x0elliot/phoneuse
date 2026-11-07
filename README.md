# airwisp

airwisp lets a Linux PC see and operate an unmodified iPhone. The phone's screen
arrives over AirPlay as a window on your desktop, and your PC acts as a Bluetooth
mouse and keyboard for the phone. You can use the mirror window like the phone
itself (hover, click to tap, drag to swipe, type), and agents can drive the phone
through a command line: take a screenshot or read the screen as text, then tap,
swipe, type or open apps.

No jailbreak, developer account, cable or app on the phone is needed. It relies
only on features every iPhone has: Screen Mirroring and AssistiveTouch.

## What you need

| | Tested with | Notes |
|---|---|---|
| iPhone | iPhone 17 Pro, iOS 26 | other models: set `screen_points` (below) |
| Linux with BlueZ | Arch Linux, BlueZ 5.87 | the Bluetooth adapter must be in range of the phone |
| Hyprland | 0.56 | window geometry and the cursor come from Hyprland's IPC |
| UxPlay (AirPlay receiver) | 1.73.7 | `uxplay` in Arch's AUR and most distros |
| GStreamer | 1.28 | NVIDIA decoding used when available, software otherwise |
| Python 3.11+ | 3.14 | with `python-dbus`, `python-gobject`, `numpy`, `pillow` |
| `grim` | | screenshots for agents |
| `uv` | | only for the optional screen-reading models |

The phone and the PC must be on the same network for AirPlay, and the PC's
Bluetooth must reach the phone. A built-in Wi-Fi/Bluetooth card needs its antenna
attached: without it the signal can be too weak to pair reliably.

## Setup

1. **Get the code** and put the command on your path:
   ```sh
   git clone https://github.com/lxe/airwisp.git ~/airwisp
   ln -s ~/airwisp/bin/airwisp ~/.local/bin/airwisp
   ```

2. **Install the Bluetooth side** (and, if `uv` is present, the screen-reading
   models):
   ```sh
   airwisp install
   ```
   This needs sudo. It configures bluetoothd so the PC can act as a mouse and
   keyboard (it disables bluetoothd's own input and hostname plugins, so this PC
   stops accepting Bluetooth keyboards and mice of its own), and runs the HID
   daemon as the `airwisp-hid` service. `sudo scripts/install.sh --uninstall`
   undoes it.

3. **Open the firewall for AirPlay**, if you run one. UxPlay uses TCP 7000, 7001,
   7100 and UDP 6000, 6001, 7011.

4. **Set up the iPhone** under Settings → Accessibility:
   - Touch → AssistiveTouch: **on**; Dwell Control: **off** (otherwise the
     pointer taps by itself when it rests).
   - Optional, for the debugging tools: Pointer Control colour **Orange**, large,
     with Automatically Hide Pointer off. `airwisp where` and the telemetry tools
     find the pointer in screenshots by this colour. Agents don't need it: every
     tap and drag starts from an exact position, so airwisp always knows where
     the pointer is.

5. **Pair**: on the iPhone, Settings → Bluetooth → tap **airwisp**. The first
   device to pair is trusted from then on (`/etc/airwisp/allowed`).

6. **Start it**:
   ```sh
   airwisp up
   ```
   Then on the iPhone: Control Center → Screen Mirroring → **airwisp**. A
   phone-shaped window appears on your desktop.

## Using it

Over the mirror window, the phone's pointer follows your cursor. Click to tap,
drag to swipe, and press on the dark bezel to start a swipe from the very edge
of the screen (from the bottom bezel upward goes home). While the mirror window
has focus, your keyboard types on the phone, and Super acts as Cmd.

For agents and scripts, every action is a subcommand. `airwisp --help` lists
them; a typical loop looks like this:

```sh
airwisp open Settings
airwisp text                 # the screen as text lines with positions
airwisp tap-on "Wi-Fi"       # find an element by description and tap it
airwisp screenshot shot.png  # when text isn't enough
airwisp back
```

`docs/RECIPES.md` lists the gestures that work, the ones that don't, and why.
`skill/SKILL.md` is a ready-made skill for Claude Code agents: link it into
`~/.claude/skills/airwisp`.

## Configuration

Optional, in `~/.config/airwisp/config.toml`:

```toml
name = "airwisp"              # Bluetooth device and AirPlay receiver name
screen_points = [402, 874]    # your iPhone's screen size in points
decoder = "auto"              # GStreamer H.264 decoder
mirror_width = 498            # mirror window width in logical pixels
```

After changing `name`, rerun `airwisp install`.

## How it works

`ARCHITECTURE.md` walks through the pieces and the iOS behaviour they were built
around, measured on a real phone.

## License

MIT
