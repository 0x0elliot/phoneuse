"""Who controls the phone: the one record every part of phoneuse reads.

States:
  idle       the owner is in control
  requested  an agent asked to start, and waits for the owner ("ask") or a countdown
             ("countdown") to end
  driving    an agent may act until `until`; every action moves `until` AGENT_IDLE s ahead
  paused     the owner took over; agents are refused until the owner resumes

Every transition happens here and nowhere else:
  idle       --act, access "auto"-------------------------> driving
  idle       --ask------------------------------------------> requested
  requested  --allow, or the countdown ends ----------------> driving
  requested  --deny, no answer, agent gave up, done --------> idle
  driving    --act-------------------------------------------> driving (until moves ahead)
  driving    --done, or AGENT_IDLE s without an action ------> idle
  any        --take over-------------------------------------> paused
  paused     --resume----------------------------------------> idle

The HID daemon's agent gate, the browser mirror, the companion app's state and Live
Activity, and the notifications all derive from this record: listeners hear about every
change (with a reason), and nothing else keeps its own copy of the session. Time-based
changes (the session running out, a countdown ending, a request going unanswered) happen
in tick(), which the server calls twice a second and every read calls too.
"""
import json
import os
import secrets
import time

from .config import config_path

AGENT_IDLE = 60.0  # s an agent session lasts after its last action (and an approval with it)
THINK_AFTER = 3.0  # s an agent quiet after acting or reading counts as thinking
ASK_WAIT = 120.0  # s a request in "ask" access waits for an answer


# "Agent control": what an agent's first action waits for.
#   auto       Always: the agent takes control at once
#   countdown  After a delay: the agent takes control when `seconds` run out, unless the owner cancels
#   ask        Ask every time: the agent waits for the owner's Allow (up to ASK_WAIT)
START_FILE = os.path.join(os.path.dirname(config_path()), "agent-start.json")
START_MODES = ("auto", "countdown", "ask")
_OLD_FLAG = os.path.join(os.path.dirname(config_path()), "ask-before-session")  # before agent-start.json


def start_setting():
    """Agent control: {"mode": auto | countdown | ask, "seconds": 5..30}."""
    try:
        with open(START_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {"mode": "ask"} if os.path.exists(_OLD_FLAG) else {}
        if d:
            set_start_setting("ask")  # moved into agent-start.json, once
    mode = d.get("mode") if d.get("mode") in START_MODES else "auto"
    return {"mode": mode, "seconds": int(min(30, max(5, d.get("seconds", 10))))}


def set_start_setting(mode=None, seconds=None):
    cur = {"mode": "auto", "seconds": 10}
    try:
        with open(START_FILE) as f:
            cur.update(json.load(f))
    except (OSError, ValueError):
        pass
    if mode in START_MODES:
        cur["mode"] = mode
    if seconds is not None:
        cur["seconds"] = int(min(30, max(5, float(seconds))))
    with open(START_FILE, "w") as f:
        json.dump(cur, f)
    if os.path.exists(_OLD_FLAG):
        os.remove(_OLD_FLAG)
    return start_setting()


class AgentSession:
    def __init__(self):
        self.state = "idle"
        self.request = None  # {"id", "action", "mode", "since", "deadline"} while requested
        self.outcome = {}  # request id -> how it ended: allowed / declined / timed out / cancelled
        self.until = 0.0  # driving: when the session runs out without another action
        self.started = 0.0  # driving: when the session started
        self.steps = 0
        self.action = ""
        self.phase, self.phase_at = "thinking", 0.0
        self.listeners = []  # f(session, old_state, why), after every change

    # ---- reading ----
    def current(self):
        self.tick()
        return self.state

    def agent(self):
        """The older three-way view: driving, paused, or idle (a request is still idle)."""
        s = self.current()
        return s if s in ("driving", "paused") else "idle"

    def current_phase(self):
        """acting, reading, or thinking once the agent has been quiet for THINK_AFTER s."""
        if self.phase in ("acting", "reading") and time.time() - self.phase_at > THINK_AFTER:
            return "thinking"
        return self.phase

    def gate(self, mode):
        """The HID daemon's agent gate: whether agents' input may reach the phone."""
        s = self.current()
        if s == "paused":
            return "closed"
        if mode == "auto":
            return "open"
        return f"until {self.until:.3f}" if s == "driving" else "closed"

    # ---- time ----
    def tick(self, now=None):
        now = now or time.time()
        if self.state == "driving" and now >= self.until:
            self._set("idle", "the agent sent no action for a while")
        elif self.state == "requested":
            r = self.request
            if r["deadline"] and now >= r["deadline"]:
                self._allow("the countdown ran out")
            elif not r["deadline"] and now >= r["since"] + ASK_WAIT:
                self._end_request("timed out", "no answer from the owner")

    # ---- transitions ----
    def ask(self, action, mode, seconds):
        """An agent wants to start (access "countdown" or "ask"). Returns the request;
        concurrent agents share it."""
        if self.current() == "requested":
            return self.request
        now = time.time()
        self.request = {"id": secrets.token_hex(8), "action": action, "mode": mode, "since": now,
                        "deadline": now + seconds if mode == "countdown" else None}
        self._set("requested", "an agent asked to start")
        return self.request

    def answer(self, rid, approve):
        """The owner's answer. False when that request is over."""
        if self.current() != "requested" or self.request["id"] != rid:
            return False
        if approve:
            self._allow("the owner allowed it")
        else:
            self._end_request("declined", "the owner declined")
        return True

    def cancel(self, why="the agent stopped waiting"):
        if self.state == "requested":
            self._end_request("cancelled", why)

    def act(self, action="", phase="acting"):
        """An agent action. False while the owner has taken over."""
        s = self.current()
        if s == "paused":
            return False
        now = time.time()
        if s != "driving":
            self.started, self.steps = now, 0
        self.steps += 1
        self.action = action or self.action
        self.phase, self.phase_at = phase, now
        self.until = now + AGENT_IDLE
        if s != "driving":
            if s == "requested":  # access was turned to "auto" while a request waited
                self._end_request("allowed", "access no longer asks", then="driving")
            else:
                self._set("driving", "an agent started")
        return True

    def set_phase(self, phase):
        if self.current() == "driving" and phase in ("reading", "thinking"):
            self.phase, self.phase_at = phase, time.time()

    def done(self):
        """The agent handed the phone back (or the owner ended its session)."""
        s = self.current()
        if s == "requested":
            self._end_request("cancelled", "the agent ended its session")
        elif s == "driving":
            self.until = 0.0
            self._set("idle", "the agent handed the phone back")

    def take_over(self):
        if self.state == "requested":
            self._end_request("cancelled", "the owner took over", then="paused")
        elif self.state != "paused":
            self.until = 0.0
            self._set("paused", "the owner took over")

    def resume(self):
        if self.state == "paused":
            self._set("idle", "the owner resumed the agent")

    # ---- internals ----
    def _allow(self, why):
        now = time.time()
        self.outcome[self.request["id"]] = "allowed"
        self.request = None
        self.started, self.steps, self.until = now, 0, now + AGENT_IDLE
        self._set("driving", why)

    def _end_request(self, outcome, why, then="idle"):
        self.outcome[self.request["id"]] = outcome
        if len(self.outcome) > 50:  # keep the answers recent waiters may still read
            for k in list(self.outcome)[:-50]:
                del self.outcome[k]
        self.request = None
        self._set(then, why)

    def _set(self, state, why):
        old, self.state = self.state, state
        for f in list(self.listeners):
            try:
                f(self, old, why)
            except Exception as e:  # a listener's failure must never stop a transition
                print(time.strftime("%H:%M:%S"), "agent session listener error:", e, flush=True)
