#!/usr/bin/env python3
"""Max-plan throttle probe daemon.

Fires `claude -p "ok"` at adaptive interval to detect Max throttle state.
Writes structured probes to scripts/.probe_log.jsonl and current state to
scripts/.probe_state.json.

State classification (over last 5 probes):
  🟢 clear     — 0 fails AND >=3 probes recorded
  🟡 ramping   — 1-2 fails (mixed)
  🔴 throttled — >=3 fails of last 5 (or 2 of last 2)
  ⚪ unknown   — <2 probes recorded

Interval:
  300s when state == clear
  60s otherwise (yellow / red / unknown)

Usage:
  python3 scripts/probe_max_throttle.py run    # foreground loop (use nohup for daemon)
  python3 scripts/probe_max_throttle.py status # one-shot read scripts/.probe_state.json
  python3 scripts/probe_max_throttle.py stop   # SIGTERM the running daemon
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PID_FILE = SCRIPT_DIR / ".probe_daemon.pid"
LOG_FILE = SCRIPT_DIR / ".probe_log.jsonl"
STATE_FILE = SCRIPT_DIR / ".probe_state.json"

CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
CLAUDE_ENV = {
    "HOME": os.path.expanduser("~"),
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "USER": os.environ.get("USER", ""),
    "SHELL": os.environ.get("SHELL", ""),
    "LANG": os.environ.get("LANG", ""),
}

PROBE_TIMEOUT = 30
INTERVAL_CLEAR = 300
INTERVAL_OTHER = 60
WINDOW = 5  # probes to classify over


# ---------------------------------------------------------------------------
# State classification
# ---------------------------------------------------------------------------

def classify_state(recent_entries):
    """Classify state from list of probe dicts (most recent last)."""
    n = len(recent_entries)
    if n < 2:
        return "unknown", "⚪"
    last5 = recent_entries[-5:]
    fails = sum(1 for e in last5 if not e["success"])
    if fails == 0 and n >= 3:
        return "clear", "🟢"
    last2_fails = sum(1 for e in recent_entries[-2:] if not e["success"])
    if last2_fails >= 2 or fails >= 3:
        return "throttled", "🔴"
    return "ramping", "🟡"


def load_recent_probes(n=WINDOW):
    """Load last n probe entries from log file."""
    if not LOG_FILE.exists():
        return []
    entries = []
    with LOG_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries[-n:] if len(entries) > n else entries


def write_state(state, emoji, last_entry, recent_entries):
    """Overwrite .probe_state.json with current classification."""
    payload = {
        "state": state,
        "emoji": emoji,
        "last_probe_at": last_entry["t"],
        "last_probe_success": last_entry["success"],
        "last_probe_latency_ms": last_entry["latency_ms"],
        "recent_count": len(recent_entries),
        "recent_fails": sum(1 for e in recent_entries if not e["success"]),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Probe execution
# ---------------------------------------------------------------------------

def run_probe():
    """Fire 'claude -p ok' and return a probe entry dict."""
    t_start = time.monotonic()
    ts = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "ok", "--output-format", "text"],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT, env=CLAUDE_ENV,
        )
        latency_ms = int((time.monotonic() - t_start) * 1000)
        # Success: returncode == 0 AND non-empty stdout
        success = (result.returncode == 0 and bool(result.stdout.strip()))
        entry = {
            "t": ts,
            "success": success,
            "latency_ms": latency_ms,
            "returncode": result.returncode,
            "stderr": (result.stderr or "")[:200],
        }
    except subprocess.TimeoutExpired:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        entry = {
            "t": ts,
            "success": False,
            "latency_ms": latency_ms,
            "returncode": -1,
            "stderr": "timeout",
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        entry = {
            "t": ts,
            "success": False,
            "latency_ms": latency_ms,
            "returncode": -2,
            "stderr": str(exc)[:200],
        }
    return entry


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

_running = True


def _handle_sigterm(signum, frame):
    global _running
    _running = False
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except OSError:
            pass
    print("[probe] SIGTERM received — daemon stopping", flush=True)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_run(_args):
    """Foreground loop. Use `nohup python3 probe_max_throttle.py run &` to daemonize."""
    global _running

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, _handle_sigterm)

    print(f"[probe] daemon started PID={os.getpid()}", flush=True)
    print(f"[probe] log={LOG_FILE}  state={STATE_FILE}", flush=True)

    while _running:
        entry = run_probe()
        # Append to log
        with LOG_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        # Reload recent window (includes the entry just written)
        recent = load_recent_probes(WINDOW)
        state, emoji = classify_state(recent)
        write_state(state, emoji, entry, recent)

        interval = INTERVAL_CLEAR if state == "clear" else INTERVAL_OTHER
        status_str = "ok" if entry["success"] else f"FAIL rc={entry['returncode']}"
        print(
            f"[probe] {entry['t']}  {emoji} {state}  probe={status_str}  "
            f"latency={entry['latency_ms']}ms  next_in={interval}s",
            flush=True,
        )

        # Sleep in 1s chunks to remain responsive to SIGTERM
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)

    if PID_FILE.exists():
        PID_FILE.unlink()
    return 0


def cmd_status(_args):
    """One-shot: read .probe_state.json and print it."""
    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found — daemon may not be running", flush=True)
        sys.exit(2)
    data = json.loads(STATE_FILE.read_text())
    print(json.dumps(data, indent=2, ensure_ascii=False), flush=True)
    return 0


def cmd_stop(_args):
    """Send SIGTERM to the running daemon."""
    if not PID_FILE.exists():
        print("ERROR: no PID file found — daemon not running?", flush=True)
        sys.exit(1)
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink()
        print(f"[probe] sent SIGTERM to PID {pid}", flush=True)
    except ProcessLookupError:
        print(f"[probe] PID {pid} not found — stale PID file removed", flush=True)
        PID_FILE.unlink()
    return 0


SUBCOMMANDS = {"run": cmd_run, "status": cmd_status, "stop": cmd_stop}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        sys.stderr.write(
            f"usage: {sys.argv[0]} {{{' | '.join(SUBCOMMANDS)}}} [args...]\n"
        )
        sys.exit(2)
    sys.exit(SUBCOMMANDS[sys.argv[1]](sys.argv[2:]) or 0)


if __name__ == "__main__":
    main()
