# phoneuse

> [!WARNING]
> **Under heavy construction.** This is a technology demo, and I have tested it on
> one setup: an iPhone 17 Pro, Arch Linux, Hyprland and an NVIDIA GPU. Other setups
> will likely need fixes.

phoneuse lets a Linux PC see and operate an unmodified iPhone. The iPhone sends its
screen to the PC over AirPlay, and the PC sends taps and keystrokes to the iPhone as
a Bluetooth mouse and keyboard. The PC can do that with its own Bluetooth adapter or
through a small ESP32 bridge that you leave next to the phone. You can use the mirror
window as you would use the phone, or let an agent operate the phone from the command
line or over MCP.

You don't need a jailbreak, a developer account, a cable or an app on the phone.
phoneuse uses two features that every iPhone has: Screen Mirroring and AssistiveTouch.

## What you need

| | Tested with |
|---|---|
| iPhone | iPhone 17 Pro, iOS 26 (for other models, set `screen_points`) |
| Linux with BlueZ | Arch Linux, BlueZ 5.87 |
| Hyprland | 0.56 |
| UxPlay | 1.73.7 |
| GStreamer, GTK 4, `gtk4paintablesink` | 1.28, 4.24 |
| Python 3.11+ | `python-dbus`, `python-gobject`, `numpy`, `pillow`, `aiohttp` |
| `grim` | takes screenshots for agents |
| `uv` (optional) | runs the models that read the screen |
| For the bridge (optional) | LilyGO T-Display (ESP32), ESP-IDF v6.1, `python-bleak`, `python-cryptography`, `python-pyserial` |

The phone and the PC must be on the same network. If you run a firewall, open TCP
ports 7000, 7001 and 7100 and UDP ports 6000, 6001 and 7011 for AirPlay, and UDP
port 47700 for the bridge. The companion app needs TCP port 8778.

## Setup

1. **Install:**
   ```sh
   git clone https://github.com/lxe/phoneuse.git ~/phoneuse
   ln -s ~/phoneuse/bin/phoneuse ~/.local/bin/phoneuse
   phoneuse install   # needs sudo
   ```
   `phoneuse install` sets up the HID daemon as the `phoneuse-hid` service. It also
   turns off bluetoothd's input plugin, so the PC stops accepting Bluetooth keyboards
   and mice for itself. To undo the install, run `sudo scripts/install.sh --uninstall`.

2. **Start phoneuse:**
   ```sh
   phoneuse up
   ```
   Then, on the iPhone, open Control Center, tap Screen Mirroring and choose
   **PhoneUse**.

3. **Connect the mouse and keyboard**, in one of two ways:
   - **With this PC's Bluetooth:** on the iPhone, open Settings › Bluetooth and tap
     **PhoneUse**.
   - **With the bridge:** follow [The Bluetooth bridge](#the-bluetooth-bridge) below.

4. **Turn on the pointer** (AssistiveTouch), in one of two ways:
   - Run `phoneuse cursor on`. phoneuse plays a spoken request through this PC's
     speakers and asks Siri to turn it on.
   - On the iPhone, open Settings › Accessibility › Touch › AssistiveTouch.

   Keep Dwell Control off: when it is on, iOS taps wherever the pointer stops. The
   first time you turn on a phone's pointer, phoneuse spends about 13 seconds
   measuring how far that phone moves the pointer for each mouse report, and it uses
   that measurement for drags. To measure again, run `phoneuse calibrate`.

## The Bluetooth bridge

The bridge is an ESP32 board that the iPhone pairs with as its Bluetooth keyboard and
mouse. phoneuse sends commands to the bridge over Wi-Fi, so you can leave the bridge
next to the phone on a battery or a charger, and the PC's own Bluetooth adapter stays
unused.

1. **Flash the bridge** once, over USB. Install ESP-IDF, then build and flash the
   firmware:
   ```sh
   git clone -b v6.1 --recursive https://github.com/espressif/esp-idf.git ~/esp/esp-idf-v6.1
   ~/esp/esp-idf-v6.1/install.sh esp32
   phoneuse bridge flash
   ```
2. **Set it up** in the browser mirror: open Settings › Bluetooth bridge › Set Up
   Bridge. Check that the bridge's screen shows the same code as the page, then pick
   a 2.4 GHz Wi-Fi network and type its password. This step doesn't need the USB
   cable.
3. **Pair the iPhone** with the bridge: on the iPhone, open Settings › Bluetooth and
   tap **PhoneUse Bridge**.

`phoneuse bridge status` shows the bridge's address, which phone is connected to it,
and how long a message takes to reach the bridge and come back. When the phone
disconnects, the bridge reconnects to it by itself. [docs/BRIDGE.md](docs/BRIDGE.md)
describes the protocol.

## Using it

**The mirror window:** the phone's pointer follows your mouse. Click to tap, drag to
swipe, and use the scroll wheel to scroll. To swipe in from an edge of the screen,
press on the bezel and drag; dragging up from the bottom bezel goes to the home
screen. While the window has focus, your keyboard types on the phone, and the Super
key works as Cmd.

**The browser mirror:** http://localhost:8777 shows the same mirror, and only this
computer can open it. In its settings you can save the passcode, set up the bridge
and keep the phone's screen awake.

**Unlocking:** when an agent runs `phoneuse unlock`, phoneuse asks you first, with a
banner in the browser mirror and a desktop notification. It types the saved passcode
only after you approve.

**Agents:** each action is a subcommand, and `phoneuse --help` lists them all:

```sh
phoneuse open Settings
phoneuse text                 # print the screen as text, with positions
phoneuse tap-on "Wi-Fi"       # tap the on-screen text that matches
phoneuse screenshot shot.png
phoneuse done                 # hand the phone back to you
```

**MCP:** the MCP server offers the same actions. After each action, it returns the
screen once the screen has stopped changing.

```sh
scripts/setup-mcp.sh
claude mcp add --scope user phoneuse ~/phoneuse/bin/phoneuse-mcp
```

[skill/SKILL.md](skill/SKILL.md) is a skill for Claude Code. To use it, link it into
`~/.claude/skills/phoneuse`.

## Configuration

These settings are optional and go in `~/.config/phoneuse/config.toml`:

```toml
name = "PhoneUse"             # the Bluetooth and AirPlay name; rerun phoneuse install after changing it
screen_points = [402, 874]    # the iPhone's screen size in points
decoder = "auto"              # the GStreamer H.264 decoder
mirror_width = 498            # the mirror window's width
web_port = 8777               # the browser mirror's port
```

## More

- [ARCHITECTURE.md](ARCHITECTURE.md) explains how the parts of phoneuse work together, and which iOS behaviours phoneuse depends on.
- [docs/RECIPES.md](docs/RECIPES.md) lists which gestures work on iOS, and why.
- [docs/BRIDGE.md](docs/BRIDGE.md) covers the ESP32 bridge's setup and protocol.

## macOS

**macOS support added.** Duh. Boring. But we have this figured.

macOS already ships both channels that phoneuse builds by hand on Linux.
**iPhone Mirroring** shows the iPhone in a window and forwards clicks and keys
to it, so there is no AirPlay receiver, no Bluetooth HID daemon, no systemd
service, no ESP32 bridge and no pairing. What [`macos/`](macos/PORT.md) adds is
the part Apple does not ship: an agent interface. Vision turns the window into
`x y  text`, words address the tap target, and synthetic clicks and keystrokes
drive the phone.

### What you need

|  | Tested with |
|---|---|
| macOS | 26.3, Apple silicon (15+ and T2 Macs have iPhone Mirroring) |
| iPhone | iPhone 17 Pro, iOS 26, paired to the same Apple ID |
| Toolchain | Xcode or Command Line Tools (`swift build`) |
| Permissions | Screen Recording and Accessibility for your terminal |

### Setup

```bash
cd macos
./install.sh        # builds release, links ~/.local/bin/phoneuse-mac
```

Then open **iPhone Mirroring**, pair the phone with the same Apple ID, and leave
the iPhone locked and idle — mirroring connects to a locked phone, and the
phone's own screen goes dark while it is connected. `phoneuse-mac status` should
end with `ready: yes`.

### Using it

Same command surface and the same 0..1 coordinate convention as the Linux CLI.
Any action can end with `--text` to read the screen afterwards.

```bash
phoneuse-mac status
phoneuse-mac text                       # "x y  text" lines, OCR'd locally
phoneuse-mac tap-on "Wi-Fi"             # tap the matching line
phoneuse-mac tap 0.5 0.35 --text
phoneuse-mac type "hello"               # replaces the field; --append keeps it
phoneuse-mac key enter
phoneuse-mac scroll down
phoneuse-mac swipe 0.5 0.8 0.5 0.2
phoneuse-mac home | switcher | spotlight
phoneuse-mac open "Settings"
phoneuse-mac screenshot shot.png
phoneuse-mac done
```

### What it does not have yet

- **No MCP server.** CLI only; the Linux repo's `look`/`tap`/`wait` tools have no
  macOS equivalent yet. This is the next piece.
- **No settle/frames logic.** `--text` sleeps 0.8 s and reads once, instead of
  waiting for the screen to stop changing and returning three frames.
- **No unlock.** Not needed: mirroring keeps the phone locked and hands you the
  session anyway. Face ID prompts inside an app still land on the phone.
- **No Control Center or notification gestures.** `back` is an edge swipe,
  `home`/`switcher`/`spotlight` click the app's View menu.

### Limits worth knowing

- The phone's own screen is off while mirroring — good for privacy, bad for
  filming: the only picture is the Mac window.
- Secure surfaces (banking apps and anything that blocks capture) can go blank.
- One Apple ID, one phone, one window.

[`macos/PORT.md`](macos/PORT.md) has the full mapping, the three things that only
a live test finds, and the reasoning behind the split.

## License

MIT
