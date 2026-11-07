# How phoneuse works

phoneuse has two independent channels to the phone. The screen comes in over
AirPlay, the same way it would go to an Apple TV, and input goes out over
Bluetooth, with the PC pretending to be a mouse and keyboard. Nothing runs on the
phone. Everything else in the repository connects these two channels: turning
clicks on the mirror window into touches, and giving agents commands and a way to
read the screen.

```
            AirPlay video (Wi-Fi)                      Bluetooth HID (mouse + keyboard)
 iPhone  ─────────────────────────▶  mirror window      ◀─────────────────────────  phoneuse-hid daemon
                                     (phoneuse up)                                      (root, systemd)
                                          │                                                 ▲
                         Hyprland IPC: where the window is, where the cursor is             │ command socket
                                          ▼                                                 │ /run/phoneuse-hid.sock
                                     mirror_input  ──── hover / press / drag / keys ────────┤
                                     phoneuse CLI   ──── tap / swipe / type / home ... ──────┘
                                          │
                                     vision service (OCR + grounding) for `phoneuse text/find`
```

## The pieces

**`phoneuse/hid_daemon.py`** runs as root under systemd (`phoneuse-hid`). It
registers a classic Bluetooth HID profile with BlueZ (the SDP record in
`sdp_record.xml`), owns the HID control and interrupt channels, and pairs with
"Just Works". Its report descriptor declares three things: a keyboard, a
relative mouse and an absolute pointer. Other programs send it one-line commands
on `/run/phoneuse-hid.sock`: `a X Y BUTTON` for the absolute pointer, `m DX DY
WHEEL BUTTON` for the relative mouse, `k MODS KEYS` and `type TEXT` for the
keyboard. It also keeps the Bluetooth link responsive (below) and only talks to
devices in `/etc/phoneuse/allowed`, trusting the first device that pairs.
`scripts/install.sh` reconfigures bluetoothd so this can work: the input plugin
would otherwise claim the HID channels, and the hostname plugin would reset the
device class from "keyboard and mouse" to "computer".

**`phoneuse up`** (`phoneuse/cli.py`) starts the AirPlay receiver (UxPlay), the
mirror window and the mirror input handler, and restarts any of them that exits. The mirror input
handler is a separate process that reloads when its code changes, so edits don't
drop the AirPlay connection.

**`phoneuse/mirror_input.py`** makes the mirror window behave like the phone's
screen. It reads mouse buttons and keys from `/dev/input` read-only, so it never
takes over the PC's mouse or keyboard, and gets the cursor position and window
geometry from Hyprland's IPC socket, which answers in about 0.03 ms.

**`phoneuse/window.py`** is the mirror window, an ordinary GTK 4 window with
Hyprland's own decorations. It fills itself with a dark bezel and draws the
phone picture in the middle with the screen's rounded corners; presses on the
bezel become touches at the nearest screen edge. A Hyprland rule floats it and
keeps its aspect ratio when you resize it, and if it ends up another shape
anyway, the picture stays aspect-fit and the bezel gets wider.

**`phoneuse/touch.py`** holds the gesture code used by agents (tap, long press,
swipe) and the measured table of how far iOS moves the pointer for each report
size.

**`phoneuse/screen.py`** finds the mirror window, captures the phone picture with
`grim`, and finds the orange pointer in a screenshot by its size and hollow
shape.

**`phoneuse/vision.py`** is an optional local service, started on first use, that
keeps two models loaded: RapidOCR with PP-OCRv6 for `phoneuse text` (every text
line with its position) and GoClick-Large, a 0.8B GUI grounding model, for
`phoneuse find` and `tap-on` ("Settings app icon" → a position). Reading a
screen as text costs an agent a few hundred tokens instead of about 1,300 for a
screenshot image.

## What iOS does with mouse input

iOS has no remote-control API and ignores HID touchscreens, so phoneuse is a
mouse, and iOS's AssistiveTouch turns mouse input into touches. Everything
below was measured on a real iPhone, mostly with `touchlab/`, a page that logs
the touch events Safari receives. When a guess and a measurement disagreed, the
measurement won, and several early guesses were wrong.

- **The absolute pointer lands exactly** where it's told, anywhere on the
  screen, within about half a percent. Hover and taps use it directly, with no
  calibration.
- **Presses only count from the absolute pointer.** A button press in a relative
  report does nothing.
- **An absolute position change while the button is held ends the touch** after
  about 90 ms, and it reads as a click. So a press must go down exactly where the
  pointer already is (the last hover position), and the release must happen
  where the touch is.
- **Drags therefore use relative motion.** After the absolute press, the touch
  follows relative reports. Those reports carry no button state: a button in a
  relative report reads as a second press or release, which gave double clicks.
- **iOS accelerates relative motion** by report size and drops motion from
  reports less than about 8 ms apart. Drags send exactly one report every 8 ms,
  empty ones included (slow drags die without them), sized from the measured
  table so the touch moves exactly as far as the cursor did. Sizes round down,
  because overshooting and correcting made the pointer vibrate. In touchlab, a
  175-point drag lands at 175 points.
- **The iPhone may poll the Bluetooth link only every ~50 ms**, which caps input
  at about 20 reports a second and makes the pointer crawl. The daemon asks for an
  8 ms poll interval with an HCI QoS Setup on every connection and every 20
  seconds, which brings acknowledgements to about 2 ms apart.
- **The daemon reconnects by itself.** While the iPhone is disconnected, it pages
  the phone with a pause between tries that grows from 5 to 30 seconds, because
  paging nonstop keeps the radio busy and makes it miss the iPhone's own
  connection attempts. A dropped link, a command sent while disconnected, or
  BlueZ seeing the phone connect cuts the pause short.
- **Some gestures are iOS's own.** Dragging along the page dots above the dock
  scrubs through home screen pages, with a click per page, and tapping the
  Dynamic Island opens a popup with a Stop Mirroring button. `docs/RECIPES.md`
  lists the gestures that work for agents.

## The mirror

UxPlay receives the AirPlay stream and passes the H.264 video on, undecoded, as
RTP over localhost (`-vrtp`, port 5600). The mirror window decodes it with
GStreamer and draws each frame as soon as it is decoded (`sync=false`), on the
GPU when NVDEC is available. Drawing in our own window lets the window be
resized and styled freely; UxPlay's own GL window crashed when resized.

iOS sends a frame only when the screen changes, and its stream doesn't declare
that frames never need reordering. A default H.264 decoder therefore keeps each
frame until the next one arrives, which GStreamer's latency tracer measured at
200 ms. `nvh264dec compliance=flexible` releases frames in about 1 ms, and the
software decoder does too. A pointer move now shows up in the mirror about
100 ms later, most of it the phone encoding and sending the video.

Audio comes along with the mirror. The playback buffer is kept at 40 ms instead
of the sink's default of up to 200 ms.

## Tools for finding out what's wrong

`tools/telemetry.py` records a session: raw mouse events, the cursor position
every 4 ms, every Bluetooth report sent (btmon), and a 60 fps video of the
mirror. `tools/telemetry_analyze.py` lines these up and tracks the pointer in
every frame, which is how the drag problems above were found. `touchlab/` shows
what iOS turns the reports into. `tools/latency.py` times pointer jumps from
report to screen, and `PHONEUSE_TRACE=1 phoneuse up` turns on GStreamer's
per-element latency tracer.
