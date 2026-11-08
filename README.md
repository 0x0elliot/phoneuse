# phoneuse

> [!WARNING]
> **Under heavy construction.** A technology demo, tested on one setup (iPhone 17
> Pro, Arch Linux, Hyprland, NVIDIA). Other setups will likely need fixes.

phoneuse lets a Linux PC see and operate an unmodified iPhone. The screen arrives
over AirPlay; input goes in as a Bluetooth mouse and keyboard, either from the PC
itself or from a small ESP32 bridge next to the phone. Use the mirror like the
phone, or let agents drive it from the command line or over MCP.

No jailbreak, developer account, cable or app on the phone: only Screen Mirroring
and AssistiveTouch.

## What you need

| | Tested with |
|---|---|
| iPhone | iPhone 17 Pro, iOS 26 (other models: set `screen_points`) |
| Linux with BlueZ | Arch Linux, BlueZ 5.87 |
| Hyprland | 0.56 |
| UxPlay | 1.73.7 |
| GStreamer, GTK 4, `gtk4paintablesink` | 1.28, 4.24 |
| Python 3.11+ | `python-dbus`, `python-gobject`, `numpy`, `pillow`, `aiohttp` |
| `grim` | screenshots for agents |
| `uv` (optional) | the screen-reading models |
| For the bridge (optional) | LilyGO T-Display (ESP32), ESP-IDF v6.1, `python-bleak`, `python-cryptography`, `python-pyserial` |

The phone and the PC must be on the same network. If you run a firewall, open TCP
7000, 7001, 7100 and UDP 6000, 6001, 7011 for AirPlay, and UDP 47700 for the bridge.

## Setup

1. **Install:**
   ```sh
   git clone https://github.com/lxe/phoneuse.git ~/phoneuse
   ln -s ~/phoneuse/bin/phoneuse ~/.local/bin/phoneuse
   phoneuse install   # sudo: the HID daemon as the phoneuse-hid service
   ```
   This turns off bluetoothd's own input plugin, so the PC stops accepting
   Bluetooth keyboards and mice. `sudo scripts/install.sh --uninstall` undoes it.

2. **Start it:**
   ```sh
   phoneuse up
   ```
   On the iPhone: Control Center › Screen Mirroring › **PhoneUse**.

3. **Connect the input**, one of:
   - **This PC's Bluetooth:** on the iPhone, Settings › Bluetooth › **PhoneUse**.
   - **The bridge:** see [The Bluetooth bridge](#the-bluetooth-bridge) below.

4. **Turn on the pointer** (AssistiveTouch), one of:
   - `phoneuse cursor on`: asks Siri out loud through this PC's speakers.
   - On the iPhone: Settings › Accessibility › Touch › AssistiveTouch.

   Keep Dwell Control off, or the pointer taps wherever it rests. The first time a
   phone's pointer is on, phoneuse measures its speed for drags (about 13 s;
   `phoneuse calibrate` reruns it).

## The Bluetooth bridge

An ESP32 board the iPhone pairs with as its keyboard and mouse. phoneuse reaches
it over Wi-Fi, so it can sit by the phone on a battery or any charger, and the
PC's Bluetooth is out of the path.

1. **Flash it** once, over USB. Install ESP-IDF, then build and flash:
   ```sh
   git clone -b v6.1 --recursive https://github.com/espressif/esp-idf.git ~/esp/esp-idf-v6.1
   ~/esp/esp-idf-v6.1/install.sh esp32
   phoneuse bridge flash
   ```
2. **Set it up** from the browser mirror: Settings › Bluetooth bridge › Set Up
   Bridge. Compare the code on its screen, pick a 2.4 GHz network, type the
   password. No cable needed.
3. **Pair**: on the iPhone, Settings › Bluetooth › **PhoneUse Bridge**.

`phoneuse bridge status` shows its address, phone and round trip. The phone
reconnects to it by itself. [docs/BRIDGE.md](docs/BRIDGE.md) covers the protocol.

## Using it

**Mirror window:** the phone's pointer follows your cursor. Click to tap, drag to
swipe, scroll to scroll, press on the bezel to swipe in from an edge (bottom bezel
upward goes home). With the window focused, your keyboard types on the phone;
Super is Cmd.

**Browser mirror:** the same at http://localhost:8777 (this computer only). Its
settings hold the passcode, the bridge and "Keep screen awake".

**Unlocking:** `phoneuse unlock` asks you first, on the browser mirror and as a
desktop notification, and types the saved passcode only after you approve.

**Agents:** every action is a subcommand (`phoneuse --help`):

```sh
phoneuse open Settings
phoneuse text                 # the screen as text with positions
phoneuse tap-on "Wi-Fi"       # tap an element by description
phoneuse screenshot shot.png
phoneuse done                 # hand the phone back
```

**MCP:** the same actions, each returning the settled screen:

```sh
scripts/setup-mcp.sh
claude mcp add --scope user phoneuse ~/phoneuse/bin/phoneuse-mcp
```

[skill/SKILL.md](skill/SKILL.md) is a ready-made Claude Code skill; link it into
`~/.claude/skills/phoneuse`.

## Configuration

Optional, in `~/.config/phoneuse/config.toml`:

```toml
name = "PhoneUse"             # Bluetooth and AirPlay name (rerun phoneuse install after changing)
screen_points = [402, 874]    # the iPhone's screen in points
decoder = "auto"              # GStreamer H.264 decoder
mirror_width = 498            # mirror window width
web_port = 8777               # browser mirror port
```

## More

- [ARCHITECTURE.md](ARCHITECTURE.md): how the pieces fit, and the iOS behaviour they rely on
- [docs/RECIPES.md](docs/RECIPES.md): gestures that work, and why
- [docs/BRIDGE.md](docs/BRIDGE.md): the ESP32 bridge

## License

MIT
