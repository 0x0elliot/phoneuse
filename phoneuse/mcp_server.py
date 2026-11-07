"""phoneuse as an MCP server (stdio), for agents: see and operate the iPhone.

Every action returns the phone's screen once it has settled, in the same call:
a small screenshot (402 x 874, one pixel per phone point, about 470 tokens) and
the screen as text lines "x y  text" with exact positions from OCR, plus on/off
switches. `look` picks what comes back: "both" (default), "text", "image" or
"none". Positions are fractions of the screen (0..1) or phone points when a
value is above 1. Same engine as the `phoneuse` CLI.

Run it with bin/phoneuse-mcp; it needs `phoneuse up` running.
"""
import contextlib
import io
import os
import sys
from typing import Literal

from PIL import Image as PILImage
from mcp.server.mcpserver import Image, MCPServer

from . import cli, touch

Look = Literal["both", "text", "image", "none"]

server = MCPServer(
    "phoneuse",
    instructions=(
        "Operate the user's real iPhone. Every action returns the settled screen (small screenshot + "
        "text with positions), so you rarely need `look` on its own. Prefer tap_on for visible text. "
        "On the lock screen call unlock (the owner approves each unlock); never type a passcode. "
        "This is the user's personal phone: ask before sending, posting, buying, deleting, or changing "
        "account or security settings. Don't tap the top centre (Dynamic Island): it can stop mirroring."),
)


def _quietly(fn):
    """Run a CLI helper: its prints are captured (stdout carries the protocol), and
    its errors (they exit) become a message."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = fn()
        return True, result if result is not None else out.getvalue().strip()
    except SystemExit:
        return False, (err.getvalue() or out.getvalue()).strip() or "failed"
    except Exception as e:  # never crash the tool call; say what went wrong
        return False, f"{type(e).__name__}: {e}"


def _screen(look):
    if look == "none":
        return []
    ok, shot = _quietly(cli.fresh_screenshot)
    if not ok:
        return [shot]
    parts = []
    try:
        if look in ("both", "image"):
            img = PILImage.open(shot).convert("RGB").resize((cli.PT[0], cli.PT[1]), PILImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            parts.append(Image(data=buf.getvalue(), format="jpeg"))
        if look in ("both", "text"):
            ok, lines = _quietly(lambda: cli.screen_text(shot=shot))
            parts.append("\n".join(f"{x:.3f} {y:.3f}  {t}" for x, y, t in lines) if ok else lines)
    finally:
        os.unlink(shot)
    return parts


def _act(action, look):
    def run():
        h = cli.hid()
        r = action(h)
        cli.acted()
        return r if isinstance(r, str) else "ok"
    cli.NOTES.clear()
    ok, msg = _quietly(run)
    if not ok:
        return [f"error: {msg}"]
    return ["\n".join([msg] + cli.NOTES)] + _screen(look)


def _pt(x, y):
    return cli.point(str(x), str(y))


@server.tool(structured_output=False)
def look(look: Look = "both") -> list:
    """The phone's screen now: small screenshot and/or text lines with positions."""
    return _screen(look)


@server.tool(structured_output=False)
def tap(x: float, y: float, look: Look = "both") -> list:
    """Tap at (x, y): fractions of the screen (0..1), or phone points if a value is above 1."""
    return _act(lambda h: touch.tap(h, *_pt(x, y)), look)


@server.tool(structured_output=False)
def tap_on(target: str, look: Look = "both") -> list:
    """Tap an element by description. Visible text is tapped exactly; text that isn't on
    screen is refused. Visual descriptions ("gear icon", "back button", "share button")
    use a grounding model: check the returned screen."""
    return _act(lambda h: cli.tap_on(h, target), look)


@server.tool(structured_output=False)
def long_press(x: float, y: float, seconds: float = 0.8, look: Look = "both") -> list:
    """Press and hold at (x, y)."""
    return _act(lambda h: touch.long_press(h, *_pt(x, y), hold=seconds), look)


@server.tool(structured_output=False)
def swipe(x0: float, y0: float, x1: float, y1: float, seconds: float = 0.3, look: Look = "both") -> list:
    """Drag from (x0, y0) to (x1, y1) over `seconds` (sliders, custom gestures)."""
    return _act(lambda h: touch.swipe(h, *_pt(x0, y0), *_pt(x1, y1), duration=seconds), look)


@server.tool(structured_output=False)
def scroll(direction: Literal["up", "down"] = "down", amount: float = 1.0, look: Look = "both") -> list:
    """Scroll the content by `amount` half-screens."""
    return _act(lambda h: cli.scroll(h, direction, amount), look)


@server.tool(structured_output=False)
def type_text(text: str, look: Look = "both") -> list:
    """Type text into the focused field (US layout); "\\n" presses Enter. The phone may
    autocorrect words: check the returned text before sending anything."""
    return _act(lambda h: cli.type_text(h, text), look)


@server.tool(structured_output=False)
def press_key(combo: str, look: Look = "both") -> list:
    """Press a key or shortcut: enter, escape, backspace, tab, arrows, cmd+space, shift+tab..."""
    return _act(lambda h: cli.key_combo(h, combo), look)


@server.tool(structured_output=False)
def open_app(name: str, look: Look = "both") -> list:
    """Open an app by name (home, Spotlight, type, Enter). Apps reopen where they were left."""
    return _act(lambda h: cli.open_app(h, name), look)


@server.tool(structured_output=False)
def navigate(to: Literal["home", "back", "switcher", "control-center", "notifications", "dismiss"],
             look: Look = "both") -> list:
    """System gestures: home screen, back (edge swipe), app switcher, Control Center,
    Notification Center, or dismiss those overlays."""
    fn = {"home": cli.home, "back": cli.back, "switcher": cli.switcher, "control-center": cli.control_center,
          "notifications": cli.notifications, "dismiss": cli.dismiss}[to]
    return _act(fn, look)


@server.tool(structured_output=False)
def unlock(look: Look = "text") -> list:
    """On the lock screen: ask the owner to approve an unlock with their saved passcode.
    Waits up to 2 minutes for their answer. You never see the passcode."""
    ok, msg = _quietly(cli.unlock_cmd)
    msg = msg.splitlines()[-1] if msg else msg
    return [msg if ok else f"error: {msg}"] + _screen(look)


@server.tool(structured_output=False)
def status() -> str:
    """Bluetooth link and mirror state; run first if anything fails."""
    return _quietly(cli.status)[1]


def main():
    os.chdir(cli.ROOT)
    server.run("stdio")


if __name__ == "__main__":
    sys.exit(main())
