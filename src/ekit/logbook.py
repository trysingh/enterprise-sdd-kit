"""Append-only action log: `<root>/.ekit/logs/actions.jsonl`, one JSON object per line.

Every event carries `seq` (1, 2, 3 …) and `prev`, the sha256 of the previous line's bytes (without its
newline; `sha256:genesis` for the first), so a deleted, inserted or edited line shows up in `verify`.
The chain and the sequence continue across rotation. The log is evidence for review, not a control:
whoever can write the file can rewrite the whole chain, so commit or ship it elsewhere if that matters.

Logging must never break a command: `append` swallows I/O errors and returns None.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

LOG_DIR = Path(".ekit") / "logs"
LOG_NAME = "actions.jsonl"
LOCK_NAME = "actions.lock"
ROTATE_BYTES = 5_000_000
GENESIS = "sha256:genesis"
MAX_STR = 500

# Filled by command handlers for the CLI wrapper to read and clear (e.g. CURRENT["gate"]).
CURRENT: dict[str, Any] = {}

_SECRET_KEY = re.compile(r"(?i)(token|secret|passw|api[_-]?key|credential|authorization)")
_SECRET_VALUES = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
]
_SECRET_FLAG = re.compile(r"(?i)(--?(?:password|token|secret|api-key)[= ])\S+")
_BARE_SECRET_FLAG = re.compile(r"(?i)^--?(?:password|token|secret|api-key)$")


# --------------------------------------------------------------------------- redaction
def redact(obj: Any) -> Any:
    """Copy of `obj` with secrets masked and long strings cut. Dict keys that look secret lose their value."""
    if isinstance(obj, dict):
        return {k: ("***" if _SECRET_KEY.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        s = _SECRET_FLAG.sub(lambda m: m.group(1) + "***", obj)
        for rx in _SECRET_VALUES:
            s = rx.sub("***", s)
        if len(s) > MAX_STR:
            s = f"{s[:MAX_STR]}…(+{len(s) - MAX_STR})"
        return s
    return obj


def redact_argv(argv: list[str]) -> list[str]:
    """Like `redact` for a command line: also masks the value that follows a bare `--token` style flag."""
    out: list[str] = []
    mask_next = False
    for a in argv:
        out.append("***" if mask_next else a)
        mask_next = bool(_BARE_SECRET_FLAG.match(a))
    return redact(out)


# --------------------------------------------------------------------------- files
def log_dir(root: Path) -> Path:
    return root / LOG_DIR


def current_file(root: Path) -> Path:
    return log_dir(root) / LOG_NAME


def rotated_files(root: Path) -> list[Path]:
    d = log_dir(root)
    return sorted(d.glob("actions-*.jsonl")) if d.is_dir() else []


def _last_line(path: Path) -> bytes | None:
    """The last non-empty line of a file, without its newline (None for a missing or empty file)."""
    try:
        size = path.stat().st_size
        if size == 0:
            return None
        with path.open("rb") as fh:
            data = b""
            pos = size
            while pos > 0:
                step = min(65536, pos)
                pos -= step
                fh.seek(pos)
                data = fh.read(step) + data
                lines = data.rstrip(b"\r\n").split(b"\n")
                if len(lines) > 1 or pos == 0:
                    return lines[-1].rstrip(b"\r") or None
    except OSError:
        return None
    return None


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _now() -> str:
    t = dt.datetime.now(dt.UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


@contextlib.contextmanager
def _lock(directory: Path) -> Iterator[None]:
    """Best-effort exclusive lock (fcntl on POSIX, msvcrt on Windows, none elsewhere)."""
    fh = open(directory / LOCK_NAME, "a+b")  # noqa: SIM115 - closed in the finally below
    kind = None
    try:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            kind = "fcntl"
        except ImportError:
            try:
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                kind = "msvcrt"
            except ImportError:
                pass
        yield
    finally:
        with contextlib.suppress(Exception):
            if kind == "fcntl":
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            elif kind == "msvcrt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        fh.close()


def _previous(root: Path) -> bytes | None:
    """Last line of the current file, else of the newest rotated file (so the chain survives rotation)."""
    last = _last_line(current_file(root))
    if last is not None:
        return last
    for f in reversed(rotated_files(root)):
        last = _last_line(f)
        if last is not None:
            return last
    return None


def append(root: Path, event: dict[str, Any]) -> dict[str, Any] | None:
    """Add `event` to the log with v/seq/ts/prev. Returns the stored record, or None if it could not be written."""
    try:
        d = log_dir(root)
        d.mkdir(parents=True, exist_ok=True)
        body = redact({k: v for k, v in event.items() if k not in ("v", "seq", "ts", "prev")})
        with _lock(d):
            cur = current_file(root)
            if cur.is_file() and cur.stat().st_size > ROTATE_BYTES:
                stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
                cur.rename(d / f"actions-{stamp}.jsonl")
            prev_raw = _previous(root)
            seq = 1
            if prev_raw is not None:
                try:
                    seq = int(json.loads(prev_raw.decode("utf-8"))["seq"]) + 1
                except (ValueError, KeyError, TypeError):
                    seq = 1        # damaged tail: `verify` reports it; keep logging
            rec = {"v": 1, "seq": seq, "ts": _now(),
                   "prev": GENESIS if prev_raw is None else _sha(prev_raw), **body}
            line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"), default=str)
            needs_nl = cur.is_file() and cur.stat().st_size > 0 and not _ends_with_newline(cur)
            with cur.open("ab") as fh:
                fh.write((b"\n" if needs_nl else b"") + line.encode("utf-8") + b"\n")
        return rec
    except (OSError, ValueError):
        return None


def _ends_with_newline(path: Path) -> bool:
    with path.open("rb") as fh:
        fh.seek(-1, os.SEEK_END)
        return fh.read(1) == b"\n"


# --------------------------------------------------------------------------- reading
def _all_files(root: Path) -> list[Path]:
    cur = current_file(root)
    return [*rotated_files(root), *([cur] if cur.is_file() else [])]


def iter_events(root: Path) -> Iterator[dict[str, Any]]:
    """Events oldest first (rotated files by name, then the current one); undecodable lines are skipped."""
    for f in _all_files(root):
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        for line in raw.split(b"\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(obj, dict):
                yield obj


def verify(root: Path) -> list[str]:
    """Problems in the chain (undecodable line, seq gap, prev mismatch); an empty list means intact."""
    problems: list[str] = []
    prev_raw: bytes | None = None
    last_seq = 0
    for f in _all_files(root):
        try:
            raw = f.read_bytes()
        except OSError as exc:
            problems.append(f"{f.name}: unreadable ({exc})")
            continue
        lines = raw.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()
        for n, line in enumerate(lines, 1):
            where = f"{f.name}:{n}"
            line = line.rstrip(b"\r")
            try:
                obj = json.loads(line.decode("utf-8"))
                if not isinstance(obj, dict):
                    raise TypeError("not an object")
            except (ValueError, TypeError, UnicodeDecodeError):
                problems.append(f"{where}: undecodable line")
                prev_raw = line
                continue
            seq = obj.get("seq")
            if seq != last_seq + 1:
                problems.append(f"{where}: seq {seq} after {last_seq} (events missing, added or reordered)")
            want = GENESIS if prev_raw is None else _sha(prev_raw)
            if obj.get("prev") != want:
                problems.append(f"{where}: prev does not match the previous line (line edited, removed or inserted)")
            last_seq = seq if isinstance(seq, int) else last_seq + 1
            prev_raw = line
    return problems


def count(root: Path) -> int:
    return sum(1 for _ in iter_events(root))


# --------------------------------------------------------------------------- who
def via() -> str:
    """`agent` when the OpenCode audit plugin (or a wrapper) set EKIT_ACTOR=agent, else `person`."""
    return "agent" if os.environ.get("EKIT_ACTOR") == "agent" else "person"


def actor(root: Path) -> str:
    from .freeze import _who
    return _who(root)


# --------------------------------------------------------------------------- gate summary for the CLI wrapper
def note_gate(res: Any) -> None:
    """Record a gate result's summary in CURRENT["gate"] (merged when `ekit gate all` runs several)."""
    g = CURRENT.setdefault("gate", {"name": res.gate, "result": "PASS", "checks": {}, "findings": [], "feature": None})
    if g["name"] != res.gate:
        g["name"] = "all"
    if not res.passed:
        g["result"] = "FAIL"
    fd = (res.context or {}).get("feature_dir")
    if fd and not g["feature"]:
        g["feature"] = Path(fd).name
    for c in res.checks:
        g["checks"][c.id] = c.status
        for f in c.findings:
            if f.level in ("error", "warn") and len(g["findings"]) < 20:
                first = (f.message.splitlines() or [""])[0]
                g["findings"].append(f"{c.id}: {first}")


# --------------------------------------------------------------------------- presentation
def summary(ev: dict[str, Any]) -> str:
    kind = str(ev.get("kind", ""))
    if kind == "cmd.start":
        return f"ekit {ev.get('cmd')} {' '.join(map(str, ev.get('args') or []))}".rstrip()
    if kind == "cmd.end":
        g = ev.get("gate")
        if g:
            first = (g.get("findings") or [None])[0]
            return f"gate {g.get('name')} {g.get('result')}" + (f" — {first}" if first else "")
        err = f" error: {ev['error']}" if ev.get("error") else ""
        return f"ekit {ev.get('cmd')} exit {ev.get('exit')}{err}"
    if kind.startswith("state."):
        return f"{kind.split('.', 1)[1]} {ev.get('feature') or 'golden core'}: {ev.get('reason') or '(no reason)'}"
    if kind == "agent.blocked":
        return f"BLOCKED {ev.get('feature')}: {ev.get('reason')}" + (f" [{ev['scenario']}]" if ev.get("scenario") else "")
    if kind == "tool.call":
        target = ev.get("path") or ev.get("command") or ""
        bad = f" [{ev.get('outcome')}]" if ev.get("outcome") not in (None, "ok") else ""
        return f"{ev.get('tool')} {target}{bad}".rstrip()
    return json.dumps({k: v for k, v in ev.items() if k not in ("v", "seq", "ts", "prev", "kind", "via")},
                      ensure_ascii=False)[:200]


def line(ev: dict[str, Any]) -> str:
    return f"{ev.get('ts')} {ev.get('seq'):>5} {ev.get('via') or '-':<6} {ev.get('kind')} {summary(ev)}"


def touches_feature(ev: dict[str, Any], feature: str) -> bool:
    """Event belongs to `feature`: its `feature` field, or a tool call on specs/<feature> / a test file of its number."""
    if ev.get("feature") == feature:
        return True
    if ev.get("kind") != "tool.call":
        return False
    path = str(ev.get("path") or "").replace("\\", "/")
    if f"specs/{feature}" in path:
        return True
    m = re.match(r"^(\d{3})-", feature)
    return bool(m and "test" in path.lower() and re.search(rf"(^|[/_-])(f?{m.group(1)})([_.-]|$)", Path(path).name))
