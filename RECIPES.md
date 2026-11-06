# Operating the iPhone with `phone`

`phone up` runs the AirPlay mirror and mouse control together; on the iPhone,
start Control Center → Screen Mirroring → Linux. Agents then use the commands
below and look at `phone screenshot`, which waits out the mirror's half-second
delay after the last action, so it always shows the result.

Coordinates are fractions of the screenshot (0 to 1), or iPhone points when any
value is above 1. The screen is 402 × 874 points.

## Loop for an agent

Take a screenshot, find the target, act, take a screenshot again. Taps land
exactly where asked, so there is no need to aim twice. Swipes land within a few
points, which is plenty for scrolling and edge gestures.

## Recipes (verified on an iPhone 17 Pro, iOS 26, November 2026)

| Goal | Command | What it does |
|---|---|---|
| Tap | `phone tap X Y` | press and release at the point |
| Long press | `phone longpress X Y [S]` | hold 0.8 s by default; opens context menus |
| Home | `phone home` | Cmd+H; works from any app |
| Back | `phone back` | swipe right from the left edge |
| App switcher | `phone switcher` | slow swipe up from the bottom, then hold |
| Control Center | `phone control-center` | slow (0.6 s) swipe down from the top-right corner |
| Notification Center | `phone notifications` | slow swipe down from the top-left |
| Close an overlay | `phone dismiss` | fast, long swipe up from the very bottom; closes Control Center, Notification Center and the switcher |
| Scroll | `phone scroll down [N]` / `up` | drags the content by N half-screens |
| Open an app | `phone open Settings` | Cmd+H, Cmd+Space, type the name, Enter |
| Type | `phone type "hello\n"` | US layout; `\n` presses Enter |
| Keys | `phone key cmd+space` | modifiers: cmd, shift, alt, ctrl |

## Things that don't work, or bite

- Avoid tapping the top centre of the screen: it hits the Dynamic Island, which
  opens the Screen Mirroring popup with a Stop Mirroring button.
- Cmd+H doesn't close Control Center or Notification Center; use `phone dismiss`.
- The mouse wheel and Cmd+Tab do nothing on iOS.
- Fast swipes down from the top are ignored; the top-edge recipes are slow on purpose.
- If the phone locks, the passcode screen appears. The agent must stop and ask the
  owner to unlock it. Never type a passcode.

## Why it works this way (HID facts measured on the device)

- The absolute pointer report lands exactly where asked, anywhere on the screen.
- Button presses count only from the absolute pointer, not from the relative mouse.
- While the button is held, iOS ignores absolute moves, so a drag is an absolute
  press, then relative motion, then release.
- iOS accelerates relative motion by report size and drops motion from reports
  that arrive less than about 8 ms apart, so drags send one report every 8 ms,
  sized from a measured table (`touch.DRAG_PTS`).

## iPhone settings this relies on

- Accessibility → Touch → AssistiveTouch: on; Dwell Control: off (otherwise a
  resting pointer taps on its own).
- Accessibility → Pointer Control: colour Orange, large size, Automatically Hide
  Pointer off (`phone where` finds the ring by colour).
- Consider Display & Brightness → Auto-Lock: Never while an agent is working.
