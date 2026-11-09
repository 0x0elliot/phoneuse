"""Phone Use's control window (GTK 4, libadwaita).

The phone itself is a web page (the browser mirror, http://localhost:PORT); this window starts
and stops the services and walks through setup: the top of the window always shows the next
thing to do (open the firewall, set up the bridge, pair the iPhone with it, start Screen
Mirroring) with the button that does it, and once all is done, the iPhone and the way to it.
Below are the settings, in the iOS app's order and words: Agent, Unlock, Phone, Bridge, iPhone
App, Network. Everything goes through the browser mirror's local API, the same one the page
uses, so the two always agree.

When this window starts the services (`phoneuse serve`), closing it keeps them running for
agents; Quit stops them. Start at Login asks the desktop (the background portal) to start
Phone Use, without its window, when the user logs in. When the services were already running
(a terminal's `phoneuse serve` or `up`), the window only shows and changes their state.
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import claude_setup, netcheck, screen  # noqa: E402
from .config import CFG, config_path  # noqa: E402

APP_ID = os.environ.get("FLATPAK_ID") or "co.lxe.PhoneUse"
PORT = CFG["web_port"]
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = f"http://localhost:{PORT}"  # the API takes changes only from its own origin
MODES = [("auto", "Always"), ("countdown", "After a delay"), ("ask", "Ask every time")]
DELAYS = [5, 10, 15, 30]
APP_STATE = os.path.join(os.path.dirname(config_path()), "app.json")  # {"login": bool}


def api(path, body=None, method=None, timeout=4):
    """The browser mirror's API. Returns the decoded JSON, or raises OSError."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method or ("GET" if body is None else "POST"),
                                 headers={"Content-Type": "application/json", "Origin": ORIGIN})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def in_thread(work, done=None):
    """Run work() off the main loop; then done(result, error) on it."""
    def run():
        try:
            r, e = work(), None
        except Exception as ex:  # noqa: BLE001 - shown to the user
            r, e = None, ex
        if done:
            GLib.idle_add(lambda: (done(r, e), False)[1])
    threading.Thread(target=run, daemon=True).start()


def services_running():
    """Whether some phoneuse instance holds the video hub's port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", screen.HUB_RTP_PORT))
        return False
    except OSError:
        return True
    finally:
        s.close()


def serve_command():
    if os.environ.get("FLATPAK_ID"):
        return ["phoneuse", "serve"]
    return [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin",
                                         "phoneuse"), "serve"]


def paired_iphones():
    try:
        from . import companion
        return len(companion.load().get("devices") or {})
    except Exception:  # noqa: BLE001
        return 0


def load_app_state():
    try:
        with open(APP_STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_app_state(**kw):
    d = load_app_state()
    d.update(kw)
    os.makedirs(os.path.dirname(APP_STATE), exist_ok=True)
    with open(APP_STATE, "w") as f:
        json.dump(d, f)


def nav_row(title, subtitle=None, on=None):
    r = Adw.ActionRow(title=title, activatable=True)
    if subtitle:
        r.set_subtitle(subtitle)
    r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
    if on:
        r.connect("activated", lambda *_: on())
    return r


def button(label, style=None, on=None):
    b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    if style:
        b.add_css_class(style)
    if on:
        b.connect("clicked", lambda *_: on())
    return b


def confirm(parent, heading, body, action, on_yes):
    d = Adw.AlertDialog(heading=heading, body=body)
    d.add_response("cancel", "Cancel")
    d.add_response("yes", action)
    d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
    d.connect("response", lambda _d, r: r == "yes" and on_yes())
    d.present(parent)


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        w, h = (int(v) for v in os.environ.get("PHONEUSE_APP_SIZE", "620x720").split("x"))  # screenshots set it
        super().__init__(application=app, title="Phone Use", default_width=w, default_height=h)
        self.app = app
        self.busy = False
        self._quiet = False
        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append("Open iPhone in Browser", "app.open")
        menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("About Phone Use", "app.about")
        sec.append("Quit", "app.quit")
        menu.append_section(None, sec)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text="Main Menu"))
        view.add_top_bar(header)
        # Three tabs: the phone (what to do next, or the iPhone), agents, and the bridge. The
        # switcher sits in the header bar, or at the bottom when the window is narrow.
        self.stack = Adw.ViewStack()
        self.phone_page, self.agents_page, self.bridge_page = (Adw.PreferencesPage() for _ in range(3))
        self.tabs = {}
        for key, page, title, icon in (("phone", self.phone_page, "Phone", "phone-symbolic"),
                                       ("agents", self.agents_page, "Agents", "co.lxe.PhoneUse-agent-symbolic"),
                                       ("bridge", self.bridge_page, "Bridge", "bluetooth-symbolic")):
            self.tabs[key] = self.stack.add_titled_with_icon(page, key, title, icon)
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        bar = Adw.ViewSwitcherBar(stack=self.stack)
        view.add_bottom_bar(bar)
        view.set_content(self.stack)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 500sp"))
        narrow.add_setter(header, "title-widget", Adw.WindowTitle(title="Phone Use"))
        narrow.add_setter(bar, "reveal", True)
        self.add_breakpoint(narrow)
        self.toasts.set_child(view)
        self.set_content(self.toasts)
        self._build()
        if os.environ.get("PHONEUSE_APP_TAB"):  # screenshots
            self.stack.set_visible_child_name(os.environ["PHONEUSE_APP_TAB"])

    # ---- layout ----
    def _build(self):
        # The next thing to do, or the iPhone.
        hero = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=12, margin_bottom=6)
        self.hero_icon = Gtk.Image(icon_name="phone-symbolic", pixel_size=56)
        self.hero_title = Gtk.Label(css_classes=["title-2"], wrap=True, justify=Gtk.Justification.CENTER)
        self.hero_sub = Gtk.Label(css_classes=["dim-label"], wrap=True, justify=Gtk.Justification.CENTER,
                                  max_width_chars=42, use_markup=True)
        self.hero_btn = Gtk.Button(halign=Gtk.Align.CENTER, margin_top=12, css_classes=["pill", "suggested-action"])
        self.hero_btn.connect("clicked", lambda *_: self.hero_action and self.hero_action())
        self.hero_action = None
        for w in (self.hero_icon, self.hero_title, self.hero_sub, self.hero_btn):
            box.append(w)
        hero.add(box)
        self.phone_page.add(hero)

        # Agent
        g = Adw.PreferencesGroup()  # the tab names it
        self.mode_row = Adw.ComboRow(title="Agent control", subtitle="What happens when an agent wants the phone",
                                     model=Gtk.StringList.new([m[1] for m in MODES]))
        self.mode_row.connect("notify::selected", self._mode_changed)
        self.delay_row = Adw.ComboRow(title="Delay", subtitle="You can stop the agent until then",
                                      model=Gtk.StringList.new([f"{d} seconds" for d in DELAYS]))
        self.delay_row.connect("notify::selected", self._mode_changed)
        self.claude_row = Adw.ActionRow(title="Claude Code")
        self.claude_btn = button("Connect", on=self._claude_clicked)
        self.claude_row.add_suffix(self.claude_btn)
        for r in (self.mode_row, self.delay_row, self.claude_row):
            g.add(r)
        self.agents_page.add(g)

        # Unlock
        g = Adw.PreferencesGroup(title="Unlock",
                                 description="Phone Use types the passcode only after you allow each Unlock.")
        self.pass_row = Adw.ActionRow(title="Passcode")
        self.pass_state = Gtk.Label(css_classes=["dim-label"], valign=Gtk.Align.CENTER)
        self.pass_row.add_suffix(self.pass_state)
        self.pass_entry = Adw.PasswordEntryRow(title="New Passcode", show_apply_button=True)
        self.pass_entry.connect("apply", self._passcode_apply)
        # rare and destructive: a quiet button in the group's header, not a row among the settings
        self.pass_forget = button("Forget…", "flat", lambda: confirm(
            self, "Forget the passcode?", "Unlock stops working until you save it again.", "Forget",
            lambda: in_thread(lambda: api("/api/passcode", method="DELETE"),
                              lambda *_: (self.toast("Passcode forgotten"), self.refresh()))))
        self.pass_forget.add_css_class("error")
        self.pass_forget.set_tooltip_text("Forget the passcode")
        g.set_header_suffix(self.pass_forget)
        for r in (self.pass_row, self.pass_entry):
            g.add(r)
        self.unlock_group = g
        self.agents_page.add(g)

        # Phone (the tab names it)
        g = Adw.PreferencesGroup()
        self.awake_row = Adw.SwitchRow(title="Keep Awake", subtitle="The screen stays on while the iPhone mirrors")
        self.awake_row.connect("notify::active", self._awake_changed)
        self.login_row = Adw.SwitchRow(title="Start at Login", subtitle="Phone Use runs in the background, so "
                                                                         "agents can use the phone")
        self.login_row.set_active(bool(load_app_state().get("login")))
        self.login_row.connect("notify::active", self._login_changed)
        g.add(self.awake_row)
        g.add(self.login_row)
        self.phone_page.add(g)

        # Bridge
        self.bridge_group = Adw.PreferencesGroup()  # the tab names it
        self.bridge_rows = []
        self.bridge_page.add(self.bridge_group)

        # iPhone App
        g = Adw.PreferencesGroup(title="iPhone App")
        self.paired_row = Adw.ActionRow(title="Paired")
        self.paired_count = Gtk.Label(css_classes=["dim-label"], valign=Gtk.Align.CENTER)
        self.paired_row.add_suffix(self.paired_count)
        g.add(self.paired_row)
        self.pair_row = nav_row("Pair iPhone App", "Allow and stop agents from the iPhone, and see what they do",
                                lambda: PairDialog(self).present(self))
        g.add(self.pair_row)
        self.phone_page.add(g)

        # Network: only until the ports are known to be open
        self.net_group = Adw.PreferencesGroup(title="Network", visible=False)
        self.fw_row = Adw.ActionRow(title="Firewall")
        self.fw_btn = button("Open Ports…", on=self._allow_network)
        self.fw_row.add_suffix(self.fw_btn)
        self.net_group.add(self.fw_row)
        self.bridge_page.add(self.net_group)

    # ---- refresh ----
    def refresh(self):
        if self.busy:
            return
        self.busy = True

        def work():
            out = {"running": services_running(), "claude": claude_setup.state(), "firewall": netcheck.detect(),
                   "confirmed": netcheck.confirmed(), "paired": paired_iphones()}
            if out["running"]:
                for key, path in (("picture", "/api/picture"), ("bridge", "/api/bridge"),
                                  ("session", "/api/session/ask"), ("awake", "/api/awake"),
                                  ("passcode", "/api/passcode")):
                    try:
                        out[key] = api(path)
                    except (OSError, ValueError):
                        out[key] = None
            if (out.get("picture") or {}).get("live"):
                netcheck.remember(mirrored=True)  # the iPhone reached this PC: the ports are open
                out["confirmed"] = True
            return out
        in_thread(work, self._show)

    def _show(self, s, err):
        self.busy = False
        if err or not s:
            return
        self._show_hero(s)
        running = s["running"]
        self._quiet = True
        sess = s.get("session") or {}
        if sess:
            self.mode_row.set_selected(next((i for i, m in enumerate(MODES) if m[0] == sess.get("mode")), 0))
            secs = sess.get("seconds", 10)
            self.delay_row.set_selected(min(range(len(DELAYS)), key=lambda i: abs(DELAYS[i] - secs)))
        self.delay_row.set_visible(sess.get("mode") == "countdown")
        if s.get("awake") is not None:
            self.awake_row.set_active(bool(s["awake"].get("on")))
        self._quiet = False
        for w in (self.mode_row, self.delay_row, self.awake_row, self.unlock_group):
            w.set_sensitive(running)

        saved = bool((s.get("passcode") or {}).get("saved"))
        self.pass_state.set_label("Saved" if saved else "Not saved")
        self.pass_entry.set_title("Replace Passcode" if saved else "Save Passcode")
        self.pass_forget.set_visible(saved)

        c = s["claude"]
        ok = c["skill"] and c["mcp"] and c["command"]
        self.claude_row.set_subtitle("Claude Code can see and use the phone" if ok
                                     else "Claude Code isn't installed" if not c["claude"]
                                     else "Let Claude Code see and use the phone")
        self.claude_btn.set_label("Disconnect" if ok else "Connect")
        self.claude_btn.set_sensitive(c["claude"] or ok)

        self.paired_row.set_visible(s["paired"] > 0)
        self.paired_count.set_label(f"{s['paired']} iPhone" + ("s" if s["paired"] != 1 else ""))
        self.pair_row.set_title("Pair Another iPhone" if s["paired"] else "Pair iPhone App")

        self._show_bridge(s.get("bridge"), running)
        st = (s.get("bridge") or {}).get("status") or {}
        self.tabs["bridge"].set_needs_attention(running and (not (s.get("bridge") or {}).get("saved")
                                                             or bool(st.get("error")) or not st.get("connected")))
        fw = s.get("firewall")
        self.net_group.set_visible(bool(fw) and not s["confirmed"])
        self.fw_row.set_subtitle(f"If {CFG['name']} is missing from Screen Mirroring on the iPhone, {fw} is "
                                 "blocking it. Open Ports lets the iPhone reach Phone Use on this network.")

    def _show_hero(self, s):
        """The first thing left to do, with the button that does it; or the iPhone."""
        pic, b = s.get("picture"), s.get("bridge") or {}
        st, saved = b.get("status") or {}, b.get("saved")
        name = GLib.markup_escape_text(CFG["name"])
        if not s["running"]:
            return self._hero("Phone Use is stopped", "Start it to see and use your iPhone here.",
                              "Start Phone Use", self.app.start_services)
        if not pic:
            return self._hero("Starting…", "", None, None)
        if not saved:
            return self._hero("Set up the bridge", "A small board next to the iPhone that it pairs with as its "
                              "keyboard and mouse. Phone Use reaches it over Wi-Fi.",
                              "Set Up Bridge", lambda: BridgeSetup(self).present(self), icon="input-keyboard-symbolic")
        if not pic.get("live"):
            fw = s.get("firewall") and not s.get("confirmed")
            return self._hero("Start Screen Mirroring",
                              f"On the iPhone, open Control Center, tap Screen Mirroring and choose <b>{name}</b>."
                              + (f" If {name} isn't listed, open the ports." if fw else ""),
                              "Open Ports…" if fw else None, self._allow_network if fw else None, quiet=True)
        if st.get("error"):
            return self._hero("The bridge is offline", "Check that it has power and is on the same Wi-Fi as this "
                              "PC.", "Try Again", self.refresh, icon="network-offline-symbolic")
        if not st.get("connected"):
            return self._hero("Connect the bridge to the iPhone", "On the iPhone, open Settings › Bluetooth and tap "
                              "PhoneUse Bridge. If it's listed as connected, keep the bridge closer to the iPhone.",
                              None, None, icon="bluetooth-symbolic")
        if pic.get("paused"):
            return self._hero("You're in control", "You took over from the agent.", "Open iPhone",
                              self.app.open_phone, good=True)
        if pic.get("stale"):
            return self._hero("The picture is old", "The iPhone's screen is off, or mirroring stalled.",
                              "Open iPhone", self.app.open_phone)
        if pic.get("lag"):
            return self._hero(f"The picture is {pic['lag']} s behind", "A screen recording on the iPhone slows "
                              "mirroring.", "Open iPhone", self.app.open_phone, good=True)
        return self._hero(st.get("phone") or "iPhone", "Mirroring to this PC", "Open iPhone",
                          self.app.open_phone, good=True)

    def _hero(self, title, sub, label, action, icon="phone-symbolic", good=False, quiet=False):
        self.hero_title.set_label(title)
        self.hero_sub.set_markup(sub)
        self.hero_sub.set_visible(bool(sub))
        self.hero_icon.set_from_icon_name(icon)
        self.hero_icon.set_css_classes(["success"] if good else ["dim-label"])
        self.hero_btn.set_visible(bool(label))
        if label:
            self.hero_btn.set_label(label)
            # quiet: a fallback, not the step itself (waiting for mirroring, the ports may be fine)
            self.hero_btn.set_css_classes(["pill"] if quiet else ["pill", "suggested-action"])
        self.hero_action = action

    def _show_bridge(self, b, running):
        for r in self.bridge_rows:
            self.bridge_group.remove(r)
        self.bridge_rows = []

        def add(r):
            self.bridge_group.add(r)
            self.bridge_rows.append(r)
        saved = (b or {}).get("saved")
        self.bridge_group.set_sensitive(running)
        self.bridge_group.set_header_suffix(None)
        if not saved:
            add(nav_row("Set Up Bridge", None, lambda: BridgeSetup(self).present(self)))
            return
        st = b.get("status") or {}
        r = Adw.ActionRow(title=f"Bridge {saved['id'][-4:]}", subtitle=saved.get("ip") or "")
        state = Gtk.Label(valign=Gtk.Align.CENTER)
        if st.get("error"):
            state.set_label("Offline")
            state.add_css_class("error")
        elif st.get("connected"):
            state.set_label(st.get("phone") or "iPhone")
            state.add_css_class("success")
        else:
            state.set_label("iPhone not connected")
            state.add_css_class("warning")
            r.set_subtitle("On the iPhone: Settings › Bluetooth › PhoneUse Bridge")
        r.add_suffix(state)
        add(r)
        use = Adw.SwitchRow(title="Input Through Bridge", subtitle="Off: you and agents can only watch",
                            active=saved.get("use", True))
        use.connect("notify::active", lambda w, _p: in_thread(lambda: api("/api/bridge/use", {"on": w.get_active()}),
                                                              lambda *_: self.refresh()))
        add(use)
        net = Adw.ActionRow(title="Wi-Fi Network", activatable=True)
        net.add_suffix(Gtk.Label(label=saved.get("ssid") or "", css_classes=["dim-label"]))
        net.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        net.connect("activated", lambda *_: BridgeSetup(self, change=True).present(self))
        add(net)
        forget = button("Forget…", "flat", lambda: confirm(
            self, "Forget the bridge?", "Phone Use stops sending input through it. To use it again, set it up "
            "again.", "Forget", lambda: in_thread(lambda: api("/api/bridge", method="DELETE"),
                                                  lambda *_: self.refresh())))
        forget.add_css_class("error")
        forget.set_tooltip_text("Forget the bridge")
        self.bridge_group.set_header_suffix(forget)

    # ---- actions ----
    def toast(self, text, undo=None):
        t = Adw.Toast(title=text, timeout=4)
        if undo:
            t.set_button_label("Undo")
            t.connect("button-clicked", lambda *_: undo())
        self.toasts.add_toast(t)

    def _mode_changed(self, *_):
        if self._quiet:
            return
        mode = MODES[self.mode_row.get_selected()][0]
        secs = DELAYS[self.delay_row.get_selected()]
        self.delay_row.set_visible(mode == "countdown")
        in_thread(lambda: api("/api/session/ask", {"mode": mode, "seconds": secs}),
                  lambda _r, e: self.toast(f"Couldn't change Agent control: {e}") if e else None)

    def _awake_changed(self, *_):
        if self._quiet:
            return
        on = self.awake_row.get_active()
        in_thread(lambda: api("/api/awake", {"on": on}),
                  lambda _r, e: self.toast(f"Couldn't change Keep Awake: {e}") if e else None)

    def _login_changed(self, *_):
        on = self.login_row.get_active()
        save_app_state(login=on)
        self.app.request_background(on)

    def _passcode_apply(self, *_):
        code = self.pass_entry.get_text()
        self.pass_entry.set_text("")
        if code:
            in_thread(lambda: api("/api/passcode", {"code": code}),
                      lambda _r, e: (self.toast(f"Couldn't save the passcode: {e}" if e else "Passcode saved"),
                                     self.refresh()))

    def _claude_clicked(self):
        if claude_setup.connected():
            in_thread(claude_setup.disconnect, lambda _r, e: (
                self.toast(f"Couldn't disconnect: {e}" if e else "Disconnected from Claude Code"), self.refresh()))
        else:
            in_thread(claude_setup.connect, lambda _r, e: (
                self.toast(f"Couldn't connect: {e}" if e else "Connected. New Claude Code sessions can use the "
                           "phone."), self.refresh()))

    def _allow_network(self):
        self.fw_btn.set_sensitive(False)
        self.hero_btn.set_sensitive(False)

        def done(msg, e):
            self.fw_btn.set_sensitive(True)
            self.hero_btn.set_sensitive(True)
            self.toast("Cancelled" if e and str(e) == "cancelled" else f"Couldn't open the ports: {e}" if e else msg)
            self.refresh()
        in_thread(netcheck.allow, done)


class PairDialog(Adw.Dialog):
    """A one-time pairing link as a QR code for the iPhone's camera; closes once the iPhone
    has paired, and makes a new code when this one runs out."""

    def __init__(self, win):
        super().__init__(title="Pair iPhone App", content_width=360)
        self.win = win
        self.before = paired_iphones()
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=24,
                           margin_start=24, margin_end=24)
        view.set_content(self.box)
        self.set_child(view)
        self.timer = GLib.timeout_add_seconds(2, self._check)
        self.connect("closed", lambda *_: GLib.source_remove(self.timer))
        self.new_code()

    def _clear(self):
        while (c := self.box.get_first_child()):
            self.box.remove(c)

    def new_code(self):
        self._clear()
        self.box.append(Adw.Spinner(height_request=48))
        self.made = time.time()
        in_thread(lambda: api("/api/companion/pair", {}, timeout=10)["link"], self._show)

    def _show(self, link, err):
        self._clear()
        if err:
            self.box.append(Gtk.Label(label=f"Couldn't make a pairing code: {err}", wrap=True))
            self.box.append(button("Try Again", "pill", self.new_code))
            return
        import io

        import qrcode
        from gi.repository import Gdk
        buf = io.BytesIO()
        qrcode.make(link, border=2, box_size=8).save(buf, format="PNG")
        tex = Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))
        self.box.append(Gtk.Picture(paintable=tex, can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN,
                                    height_request=260, css_classes=["card"]))
        self.box.append(Gtk.Label(label="Point the iPhone's camera at the code and open the link in Phone Use.",
                                  wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"]))

    def _check(self):
        if paired_iphones() > self.before:
            self.win.toast("iPhone App paired")
            self.win.refresh()
            self.close()
            return False
        if time.time() - self.made > 590:  # the code lasts 10 minutes
            self.new_code()
        return True


class BridgeSetup(Adw.Dialog):
    """Set up a bridge (find it over Bluetooth, compare the code on its screen, pick a Wi-Fi
    network, type its password, then wait for the iPhone to connect to it), or move a set-up
    bridge to another network."""

    def __init__(self, win, change=False):
        super().__init__(title="Wi-Fi Network" if change else "Set Up Bridge", content_width=420,
                         content_height=540)
        self.win, self.change, self.waiting = win, change, None
        self.nav = Adw.NavigationView()
        self.set_child(self.nav)
        self.connect("closed", self._closed)
        self.networks() if change else self.find()

    def _closed(self, *_):
        if self.waiting:
            GLib.source_remove(self.waiting)
        if not self.change:
            in_thread(lambda: api("/api/bridge/cancel", {}))
        self.win.refresh()

    def _page(self, title, *groups, actions=()):
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        for g in groups:
            page.add(g)
        if actions:
            g = Adw.PreferencesGroup()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, margin_top=6)
            for label, style, fn in actions:
                box.append(button(label, style, fn))
            g.add(box)
            page.add(g)
        tv.set_content(page)
        p = Adw.NavigationPage(title=title, child=tv)
        self.nav.push(p) if self.nav.get_visible_page() else self.nav.add(p)
        return p

    def _text(self, text, big=False):
        g = Adw.PreferencesGroup()
        g.add(Gtk.Label(label=text, wrap=True, justify=Gtk.Justification.CENTER, margin_top=12,
                        css_classes=["title-1", "numeric"] if big else ["dim-label"]))
        return g

    def _wait(self, title, text):
        g = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=24)
        box.append(Adw.Spinner(height_request=32))
        box.append(Gtk.Label(label=text, css_classes=["dim-label"], wrap=True, justify=Gtk.Justification.CENTER))
        g.add(box)
        self._page(title, g)

    def _error(self, title, text, retry):
        self._page(title, self._text(text), actions=[("Try Again", "pill", retry)])

    def find(self):
        self._wait("Find the Bridge", "Looking for bridges near this PC over Bluetooth…")
        in_thread(lambda: api("/api/bridge/find", {}, timeout=30), self._found)

    def _found(self, j, err):
        if err or (j or {}).get("error"):
            return self._error("Find the Bridge", str(err or j["error"]), self.find)
        if not j["bridges"]:
            return self._error("Find the Bridge", "No bridge found. Plug it in and keep it near this PC. A bridge "
                               "that's already set up shows up again after you hold its lower button for 3 seconds.",
                               self.find)
        g = Adw.PreferencesGroup(description="Choose the bridge to set up.")
        for b in j["bridges"]:
            g.add(nav_row(b.get("name") or "PhoneUse Bridge", b["address"], lambda a=b["address"]: self.pair(a)))
        self._page("Find the Bridge", g)

    def pair(self, address):
        self._wait("Check the Code", "Connecting to the bridge…")
        in_thread(lambda: api("/api/bridge/pair", {"address": address}, timeout=40), self._paired)

    def _paired(self, j, err):
        if err or (j or {}).get("error"):
            return self._error("Check the Code", str(err or j["error"]), self.find)
        self._page("Check the Code", self._text(j["code"], big=True),
                   self._text("Check that the bridge's screen shows the same code."),
                   actions=[("The Codes Match", "suggested-action pill", self.networks),
                            ("They Don't Match", "pill", self.find)])

    def networks(self):
        self._wait("Choose a Network", "Asking the bridge which networks it sees…")
        in_thread(lambda: api("/api/bridge/networks", {}, timeout=30), self._networks)

    def _networks(self, j, err):
        if err or (j or {}).get("error"):
            return self._error("Choose a Network", str(err or j["error"]), self.networks)
        g = Adw.PreferencesGroup(description="The bridge works on 2.4 GHz Wi-Fi. Choose the network this PC is on.")
        for n in j["networks"]:
            if not n.get("s"):
                continue
            r = nav_row(n["s"], None, lambda n=n: self.password(n["s"], n.get("l")))
            if n.get("l"):
                r.add_prefix(Gtk.Image(icon_name="channel-secure-symbolic"))
            g.add(r)
        g.add(nav_row("Other Network…", None, self.other))
        self._page("Choose a Network", g)

    def other(self):
        g = Adw.PreferencesGroup()
        name = Adw.EntryRow(title="Network Name")
        pw = Adw.PasswordEntryRow(title="Password")
        g.add(name)
        g.add(pw)
        self._page("Other Network", g, actions=[("Join", "suggested-action pill",
                                                 lambda: name.get_text() and self.join(name.get_text(), pw.get_text()))])

    def password(self, ssid, locked):
        if not locked:
            return self.join(ssid, "")
        g = Adw.PreferencesGroup()
        e = Adw.PasswordEntryRow(title=f"Password for {ssid}", show_apply_button=True)
        e.connect("apply", lambda *_: self.join(ssid, e.get_text()))
        g.add(e)
        self._page("Wi-Fi Password", g)
        e.grab_focus()

    def join(self, ssid, password):
        self._wait("Joining", f"The bridge is joining {ssid}…")
        in_thread(lambda: api("/api/bridge/join", {"ssid": ssid, "password": password}, timeout=60),
                  lambda j, err: self._joined(j, err, ssid))

    def _joined(self, j, err, ssid):
        if err or (j or {}).get("error"):
            return self._error("Joining", str(err or j["error"]), self.networks)
        if self.change:
            self.win.toast(f"The bridge is on {ssid}")
            return self.close()
        self._wait("Connect the iPhone", "On the iPhone, open Settings › Bluetooth and tap PhoneUse Bridge.")
        self.waiting = GLib.timeout_add_seconds(2, self._phone_check)

    def _phone_check(self):
        def done(b, _e):
            st = (b or {}).get("status") or {}
            if st.get("connected") and self.waiting:
                GLib.source_remove(self.waiting)
                self.waiting = None
                self._page("Bridge Ready", self._text(f"The bridge is connected to {st.get('phone') or 'the iPhone'}."),
                           actions=[("Done", "suggested-action pill", self.close)])
        in_thread(lambda: api("/api/bridge"), done)
        return True


class App(Adw.Application):
    def __init__(self):
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if os.environ.get("PHONEUSE_APP_SIZE"):  # a screenshot run: never activate the real window instead
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.proc = None  # the `phoneuse serve` this window started
        self.win = None
        for name, fn in (("open", lambda *_: self.open_phone()), ("about", lambda *_: self.about()),
                         ("quit", lambda *_: self.quit_all())):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", fn)
            self.add_action(a)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_command_line(self, cmd):
        # --background (Start at Login): start the services without the window
        if "--background" in cmd.get_arguments()[1:]:
            if not services_running():
                self.start_services()
            elif not self.proc:
                return 0
            self.hold()
            self.release()
            return 0
        self.activate()
        return 0

    def do_activate(self):
        if not os.environ.get("FLATPAK_ID"):  # a checkout: the app's own icons live in packaging/icons
            from gi.repository import Gdk
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(
                os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "packaging", "icons"))
        if not self.win:
            self.win = Window(self)
            self.win.connect("close-request", self._on_close)
            GLib.timeout_add_seconds(2, lambda: (self.win.refresh(), True)[1])
            if not services_running():
                self.start_services()
        self.win.present()
        self.win.refresh()

    def _on_close(self, *_):
        if self.proc:  # the services keep running for agents; the window comes back on the next launch
            self.win.set_visible(False)
            return True
        return False

    def start_services(self):
        if services_running():
            return self.win and self.win.refresh()
        self.proc = Gio.Subprocess.new(serve_command(), Gio.SubprocessFlags.NONE)
        self.hold()
        self.proc.wait_async(None, self._services_ended)

    def _services_ended(self, proc, _res):
        if proc is self.proc:
            self.proc = None
            self.release()
            if self.win:
                self.win.refresh()

    def quit_all(self):
        if self.proc:
            self.proc.send_signal(15)
        self.quit()

    def open_phone(self):
        Gtk.UriLauncher.new(f"http://localhost:{PORT}").launch(self.win, None, None)

    def about(self):
        Adw.AboutDialog(application_name="Phone Use", application_icon=APP_ID, developer_name="Aleksey Smolenchuk",
                        version="0.1.0", website="https://github.com/lxe/phoneuse",
                        license_type=Gtk.License.MIT_X11).present(self.win)

    def request_background(self, on):
        """Start at Login through the desktop's background portal (works in and out of the Flatpak)."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            opts = {"reason": GLib.Variant("s", "Phone Use keeps running so agents can use the iPhone"),
                    "autostart": GLib.Variant("b", on),
                    "commandline": GLib.Variant("as", ["phoneuse-app", "--background"]),
                    "dbus-activatable": GLib.Variant("b", False)}
            bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                          "org.freedesktop.portal.Background", "RequestBackground",
                          GLib.Variant("(sa{sv})", ("", opts)), None, Gio.DBusCallFlags.NONE, 10000, None)
        except GLib.Error as e:
            self.win.toast(f"Couldn't change Start at Login: {e.message}")


def main():
    Adw.init()
    sys.exit(App().run(sys.argv))


if __name__ == "__main__":
    main()
