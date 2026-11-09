"""Connect Claude Code to Phone Use: the skill, the MCP server and the `phoneuse` command.

Inside the Flatpak, each piece runs the app's own copy (`flatpak run --command=...`); from a
checkout, the checkout's. state() says which pieces are in place; connect() and disconnect()
add or remove all three. Nothing else in ~/.claude or ~/.claude.json changes.
"""
import json
import os
import shutil

HOME = os.path.expanduser("~")
SKILL_DIR = os.path.join(HOME, ".claude", "skills", "phoneuse")
CLAUDE_JSON = os.path.join(HOME, ".claude.json")
BIN = os.path.join(HOME, ".local", "bin", "phoneuse")
PKG = os.path.dirname(os.path.realpath(__file__))
FLATPAK_ID = os.environ.get("FLATPAK_ID")
MARK = "# Phone Use"  # the first comment line of the command we write, so we only ever remove our own


def _skill_source():
    for d in (os.path.join(os.path.dirname(PKG), "skill"), "/app/share/phoneuse/skill"):
        if os.path.exists(os.path.join(d, "SKILL.md")):
            return d
    return None


def _mcp_command():
    if FLATPAK_ID:
        return {"type": "stdio", "command": "flatpak", "args": ["run", "--command=phoneuse-mcp", FLATPAK_ID], "env": {}}
    return {"type": "stdio", "command": os.path.join(os.path.dirname(PKG), "bin", "phoneuse-mcp"), "args": [], "env": {}}


def _cli_script():
    target = (f"flatpak run --command=phoneuse {FLATPAK_ID}" if FLATPAK_ID
              else os.path.join(os.path.dirname(PKG), "bin", "phoneuse"))
    return f"#!/bin/sh\n{MARK}: lets agents (and you) run phoneuse commands.\nexec {target} \"$@\"\n"


def _read_json():
    try:
        with open(CLAUDE_JSON) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _write_json(d):
    # In place: inside the Flatpak only this one file is visible, not its directory, so a
    # temporary file beside it can't be made. The text is made first, so a failure leaves
    # the old file as it was.
    text = json.dumps(d, indent=2)
    with open(CLAUDE_JSON, "w") as f:
        f.write(text)


def state():
    """{"skill", "mcp", "command"}: each True when that piece is in place, and "claude": whether
    Claude Code looks installed (~/.claude exists)."""
    mcp = (_read_json().get("mcpServers") or {}).get("phoneuse") or {}
    want = _mcp_command()
    cmd_ok = False
    try:
        with open(BIN) as f:
            cmd_ok = f.read() == _cli_script()
    except OSError:
        cmd_ok = os.path.realpath(BIN) == os.path.join(os.path.dirname(PKG), "bin", "phoneuse")
    return {"claude": os.path.isdir(os.path.join(HOME, ".claude")),
            "skill": os.path.exists(os.path.join(SKILL_DIR, "SKILL.md")),
            "mcp": mcp.get("command") == want["command"] and mcp.get("args", []) == want["args"],
            "command": cmd_ok}


def connected():
    s = state()
    return s["skill"] and s["mcp"] and s["command"]


def connect():
    src = _skill_source()
    if not src:
        raise RuntimeError("the skill isn't in this copy of Phone Use")
    if os.path.islink(SKILL_DIR) or os.path.isfile(SKILL_DIR):
        os.remove(SKILL_DIR)
    elif os.path.isdir(SKILL_DIR):
        shutil.rmtree(SKILL_DIR)
    shutil.copytree(src, SKILL_DIR)
    d = _read_json()
    d.setdefault("mcpServers", {})["phoneuse"] = _mcp_command()
    _write_json(d)
    os.makedirs(os.path.dirname(BIN), exist_ok=True)
    if os.path.islink(BIN) or os.path.exists(BIN):
        os.remove(BIN)
    with open(BIN, "w") as f:
        f.write(_cli_script())
    os.chmod(BIN, 0o755)


def disconnect():
    if os.path.isdir(SKILL_DIR) and not os.path.islink(SKILL_DIR):
        shutil.rmtree(SKILL_DIR)
    elif os.path.islink(SKILL_DIR):
        os.remove(SKILL_DIR)
    d = _read_json()
    if (d.get("mcpServers") or {}).pop("phoneuse", None) is not None:
        _write_json(d)
    try:
        with open(BIN) as f:
            ours = MARK in f.read()
    except OSError:
        ours = False
    if ours:
        os.remove(BIN)
