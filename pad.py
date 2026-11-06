#!/usr/bin/env python
"""Use this PC's mouse and keyboard on the iPhone, KVM style.

Click the window to capture: mouse motion, buttons, wheel and every key go to
the iPhone through hidd. Press Right Ctrl to release. Super is the iPhone's
Cmd key (Super+H home, Super+Space search, Super+Tab app switcher).
"""
import os
import socket
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "wayland")
import pygame  # noqa: E402

SOCK_PATH = "/run/iphone-hid.sock"
RELEASE_KEY = pygame.K_RCTRL
SPEED = float(os.environ.get("PAD_SPEED", "1.0"))  # PC mouse units -> HID units
SEND_EVERY = 0.008  # seconds between mouse reports (125 Hz)
BUTTON_BITS = {1: 1, 3: 2, 2: 4}  # pygame left/right/middle -> HID bits


class Link:
    """Persistent connection to hidd; replies are read and discarded in a thread."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(SOCK_PATH)
        self.last_error = ""
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.sock.makefile():
            if line.startswith("err"):
                self.last_error = line.strip()[4:]
            elif self.last_error and line.startswith("ok"):
                self.last_error = ""

    def send(self, line):
        with self.lock:
            self.sock.sendall((line + "\n").encode())

    def ask(self, line):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCK_PATH)
        s.sendall((line + "\n").encode())
        reply = s.makefile().readline().strip()
        s.close()
        return reply


def main():
    pygame.init()
    screen = pygame.display.set_mode((460, 200), pygame.RESIZABLE)
    pygame.display.set_caption("iPhone control")
    window = pygame.Window.from_display_module()
    font = pygame.font.SysFont("sans", 17)
    small = pygame.font.SysFont("sans", 14)
    link = Link()
    captured = False
    buttons = 0
    held = []  # HID usage codes of held non-modifier keys, in press order
    mods = 0
    acc_x = acc_y = 0.0
    wheel = 0
    last_send = 0.0
    status = link.ask("status")

    def set_capture(on):
        nonlocal captured, buttons, held, mods
        captured = on
        pygame.mouse.set_relative_mode(on)
        window.grab_mouse = on
        window.grab_keyboard = on  # also keeps Super combos away from Hyprland
        if not on:  # let go of everything on the phone
            buttons, held, mods = 0, [], 0
            link.send("m 0 0 0 0")
            link.send("k 0")

    def send_keys():
        link.send("k %d %s" % (mods, " ".join(str(c) for c in held[-6:])))

    clock = pygame.time.Clock()
    last_status = time.time()
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.WINDOWFOCUSLOST and captured:
                set_capture(False)
            elif not captured:
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    set_capture(True)
            elif ev.type == pygame.KEYDOWN and ev.key == RELEASE_KEY:
                set_capture(False)
            elif ev.type == pygame.MOUSEMOTION:
                acc_x += ev.rel[0] * SPEED
                acc_y += ev.rel[1] * SPEED
            elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and ev.button in BUTTON_BITS:
                bit = BUTTON_BITS[ev.button]
                buttons = buttons | bit if ev.type == pygame.MOUSEBUTTONDOWN else buttons & ~bit
                link.send("m 0 0 0 %d" % buttons)
            elif ev.type == pygame.MOUSEWHEEL:
                wheel += ev.y
            elif ev.type in (pygame.KEYDOWN, pygame.KEYUP):
                sc = ev.scancode  # SDL scancodes are USB HID usage codes
                down = ev.type == pygame.KEYDOWN
                if 224 <= sc <= 231:
                    bit = 1 << (sc - 224)
                    mods = mods | bit if down else mods & ~bit
                elif 0 < sc < 224:
                    if down and sc not in held:
                        held.append(sc)
                    elif not down and sc in held:
                        held.remove(sc)
                send_keys()

        now = time.time()
        if captured and (acc_x or acc_y or wheel) and now - last_send >= SEND_EVERY:
            dx = max(-127, min(127, int(acc_x)))
            dy = max(-127, min(127, int(acc_y)))
            w = max(-127, min(127, wheel))
            if dx or dy or w:
                link.send("m %d %d %d %d" % (dx, dy, w, buttons))
                acc_x -= dx
                acc_y -= dy
                wheel -= w
                last_send = now
        if now - last_status > 2:
            status = link.ask("status")
            last_status = now

        connected = "connected=True" in status
        screen.fill((24, 20, 32) if not captured else (20, 60, 40))
        if not connected:
            lines = ["iPhone not connected", "Turn on Bluetooth on the phone, or run: hidctl connect"]
        elif captured:
            lines = ["Controlling the iPhone", "Right Ctrl releases your mouse and keyboard"]
        else:
            lines = ["Click here to control the iPhone", "Right Ctrl releases"]
        y = 30
        for i, text in enumerate(lines):
            surf = (font if i == 0 else small).render(text, True, (235, 235, 240))
            screen.blit(surf, (24, y))
            y += 34 if i == 0 else 24
        tips = "Super+H home   Super+Space search   Super+Tab apps"
        screen.blit(small.render(tips, True, (170, 170, 185)), (24, y + 20))
        if link.last_error:
            screen.blit(small.render(link.last_error, True, (240, 120, 120)), (24, y + 46))
        pygame.display.flip()
        clock.tick(250)

    if captured:
        set_capture(False)
        time.sleep(0.05)
    pygame.quit()


if __name__ == "__main__":
    main()
