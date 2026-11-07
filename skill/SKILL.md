---
name: airwisp
description: See and operate the user's iPhone from this Linux PC with the `airwisp` CLI (AirPlay mirror for the screen, Bluetooth mouse/keyboard for input). Use when a task needs the iPhone: open or use an app, read what is on the phone screen, tap, type, swipe, check a notification, change a phone setting, or test something on the device. Also use when the mirror or the Bluetooth link needs starting or fixing.
---

# Operating the iPhone with airwisp

The `airwisp` command drives a real, unmodified iPhone. Its screen arrives as an AirPlay mirror window on this PC, and
input goes in as a Bluetooth mouse and keyboard. Everything an agent does is a
`airwisp` subcommand; run `airwisp --help` for the full list.

## Before acting

1. Run `airwisp status`. You need `HID service: active`, `connected=True`, and a
   line `Mirror window: [x, y] [w, h]` (not "none").
2. No mirror window: check whether `airwisp up` is running. If it isn't, start it
   somewhere the user can see it (a terminal or tmux window they use), not hidden in
   the background. Then ask the user to start Screen Mirroring to "airwisp" from the
   iPhone's Control Center. You can't start mirroring from the PC.
3. The mirror window must be visible and uncovered: screenshots capture that area
   of the screen, so another window on top of it is what you'd see.
4. `connected=False`: run `airwisp status` again after a few seconds (the daemon
   reconnects), then ask the user to tap "airwisp" in the iPhone's Bluetooth settings.
5. HID service not active: `airwisp install` (needs sudo) sets it up.

## The loop

Look, decide, act, look again. Look with text first; it costs a few hundred
tokens, where a screenshot image costs about 1,300.

```bash
airwisp text                         # every text line on screen: "x y  text"
airwisp tap-on "Wi-Fi"               # find an element by description and tap it
airwisp find "clear search (X) button"   # just the position, to tap or swipe yourself
```

`airwisp text` and `airwisp find` run local models (PP-OCRv6 OCR and the GoClick
grounding model) through a service that starts on first use (first call takes
a few seconds). `find` and `tap-on` take plain descriptions, including icons
without text ("Settings app icon", "back button", "share button").

`find` always returns a position, even when the element isn't on screen, so
confirm with `airwisp text` (or a screenshot) when it matters. `tap-on` refuses
targets in the status bar, where such misses tend to land.

Take a real screenshot when text isn't enough: pictures, icon-only screens,
checking a layout, or when `find` lands somewhere surprising.

```bash
airwisp screenshot $SCRATCH/s1.png   # then look at the image with the Read tool
airwisp tap 0.5 0.35                 # fractions of the screenshot (x, y)
airwisp screenshot $SCRATCH/s2.png   # waits out the ~0.5 s mirror lag by itself
```

Write screenshots into your own scratch directory with a new name each time,
so you never read a stale image. `airwisp screenshot` moves the orange pointer to
the left edge first so it doesn't cover text (`--keep-pointer` to see where the
pointer is). The grey AssistiveTouch button near the lower right stays on screen
and can hide what is under it; scroll a little if you need that spot.

Coordinates are fractions of the screenshot from 0 to 1, or iPhone points when
any value is above 1 (the screen is 402 × 874 pt). To tap something, read its
centre off the screenshot and divide by the image size. Taps land exactly; one
try is enough.

## Commands that work (verified on the device)

| Goal | Command |
|---|---|
| Open an app | `airwisp open Settings` (Cmd+H, Cmd+Space, type the name, Enter) |
| Tap / long press | `airwisp tap X Y` · `airwisp longpress X Y [seconds]` |
| Swipe or drag | `airwisp swipe X0 Y0 X1 Y1 [seconds]` |
| Scroll | `airwisp scroll down [N]` · `airwisp scroll up [N]` (N half-screens) |
| Back | `airwisp back` (finger sliding in from the very left edge) |
| Home | `airwisp home` |
| App switcher | `airwisp switcher` |
| Control Center / Notification Center | `airwisp control-center` · `airwisp notifications` |
| Close those overlays | `airwisp dismiss` (Cmd+H does not close them) |
| Type text / keys | `airwisp type "hello\n"` · `airwisp key cmd+space` |
| Where is the pointer | `airwisp where` |

``docs/RECIPES.md` in the airwisp repository` explains why each gesture works the way it does. Read
it before inventing a new gesture with `airwisp swipe`.

## Apps reopen where they were left

`airwisp open` brings an app back in whatever state it was last in: a detail
sheet, a settings sub-page, a half-scrolled list. Check the first screenshot
before trusting what it shows. A sheet with an X or "Done" in a top corner is a
leftover; close it, or `airwisp back` until you reach the app's main view.

## Rules

- **Passcode screen:** if a screenshot shows the lock screen asking for a passcode
  (Emergency / Cancel), stop and ask the user to unlock the phone. Never type a
  passcode or try to guess one.
- **Don't tap the top centre** (the Dynamic Island, roughly x 0.35–0.65, y < 0.06):
  it opens the Screen Mirroring popup, whose Stop Mirroring button cuts the screen
  feed.
- **This is the user's personal phone.** Messages, notifications, badges and photos on
  it are private. Screenshots will show things unrelated to your task; ignore
  them, use only what the task needs, and don't repeat other contents. Ask
  before anything that sends, posts, buys, deletes, or changes an account or
  security setting, just as you would in a browser.
- **Permission prompts** ("Allow notifications?" and the like) belong to the user.
  Leave them, or ask, unless the task is about that permission.
- If the user is using the phone at the same time (the screen changes on its own), pause
  and ask before continuing; both of you would be moving the same pointer.

## When something misbehaves

- A tap or swipe seems to miss: take a fresh screenshot first. The mirror trails
  the phone slightly, so an earlier screenshot may be stale.
- You never need to locate the pointer to act: taps and drags start from exact
  positions. `airwisp where` (a debugging aid) finds it only if Pointer Control's
  colour is Orange; "not found" otherwise is normal.
- Taps happen on their own wherever the pointer rests: Dwell Control is on. Ask
  the user to turn it off (Accessibility → Touch → AssistiveTouch → Dwell Control).
