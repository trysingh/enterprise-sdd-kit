"""Deterministic constitution ratification and the principles I–VIII integrity check (ekit 0.3.0).

Before 0.3.0, `/speckit.constitution` (a model, on the flagship tier) filled the placeholders of the
enterprise template — project name, version, dates, stack section — and was trusted not to reword
principles I–VIII, which only pull-request review protected. Both are mechanical:

  * `ratify` fills every placeholder from the project itself (name, stack, today) and removes the
    unused principle IX placeholder, without a model. It never touches a ratified file's text.
  * `principles_drift` compares principles I–VIII in `.specify/memory/constitution.md` with the
    pinned kit template, ignoring whitespace; `BASE-CONSTITUTION` fails on any difference.

`/speckit.constitution` is still how a team adds project principles IX and above.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path
from typing import Any

from .project import EkitError, dump_yaml, load_yaml

MEMORY = ".specify/memory/constitution.md"
TEMPLATE = "templates/constitution-template.md"
PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*\]")
LOCK = ".ekit/constitution.lock.yaml"
TEAM = ["V", "VI", "VII", "VIII"]   # 0.6.0: in a brownfield project a person may lock the team's own V–VIII
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]
_HEADING_RE = re.compile(r"^###\s+([IVXLC]+)\.\s*(.*)$")


def template_path(project: Any) -> Path:
    return project.kit.component("preset") / TEMPLATE


def placeholders(text: str) -> list[str]:
    return sorted(set(PLACEHOLDER_RE.findall(text)))


def _stack_section(project: Any) -> str:
    lines = [f"- **Stack**: `{project.stack_id}` — {project.stack.get('description', '')}"]
    for prof in project.profiles:
        rt = prof.data.get("runtime") or {}
        ver = f" {rt['version']}" if rt.get("version") else ""
        lines.append(f"- **{prof.role}**: `{prof.id}` ({rt.get('language', '?')}{ver}), code root "
                     f"`{project.rel(prof.root) or '.'}`")
    mode = ((project.config or {}).get("baseline") or {}).get("mode")
    if mode:
        lines.append(f"- **Landing zone**: {mode}" + (" (kit golden landing zone, core frozen)" if mode == "golden" else ""))
    lines.append("- Run `ekit context` for toolchain, layout, commands and how each NFR is met.")
    return "\n".join(lines)


def ratify(project: Any, *, name: str | None = None, today: dt.date | None = None) -> list[str]:
    """Fill the template placeholders. Returns what changed (empty if nothing was left to fill)."""
    mem = project.root / MEMORY
    if not mem.is_file():
        tpl = template_path(project)
        if not tpl.is_file():
            raise EkitError(f"No {MEMORY} and no kit constitution template to seed it from.")
        mem.parent.mkdir(parents=True, exist_ok=True)
        mem.write_text(tpl.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    text = mem.read_text(encoding="utf-8")
    before = placeholders(text)
    if not before:
        return []
    day = (today or dt.date.today()).isoformat()
    proj = name or (project.config or {}).get("name") or project.root.name
    text = re.sub(r"^\[PRINCIPLE_9_NAME\]\s*\n\[PRINCIPLE_9_DESCRIPTION\]\s*\n", "", text, flags=re.M)
    text = text.replace("<!-- Optional project-specific principles. Remove these placeholders if none. -->",
                        "<!-- Project principles IX+ are added with /speckit.constitution; they may tighten, never loosen I–VIII. -->")
    text = (text.replace("[PROJECT_NAME]", proj)
                .replace("[SECTION_2_CONTENT]", _stack_section(project))
                .replace("[CONSTITUTION_VERSION]", "1.0.0")
                .replace("[RATIFICATION_DATE]", day)
                .replace("[LAST_AMENDED_DATE]", day))
    mem.write_text(text, encoding="utf-8", newline="\n")
    left = placeholders(text)
    return [f"filled {', '.join(p for p in before if p not in left)}"] + (
        [f"!! still unfilled (not a kit placeholder): {', '.join(left)}"] if left else [])


def principles(text: str) -> dict[str, str]:
    """Principle number -> whitespace-normalised text (heading + body), for I–VIII."""
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if cur in ROMAN:
            out[cur] = " ".join(" ".join(buf).split())

    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        m = _HEADING_RE.match(line.strip())
        if m or line.startswith("## ") or line.strip().startswith("[PRINCIPLE_"):
            flush()
            cur, buf = (m.group(1), [m.group(2)]) if m else (None, [])
            continue
        if cur:
            buf.append(line)
    flush()
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_lock(root: Path) -> dict[str, Any] | None:
    p = root / LOCK
    return (load_yaml(p) or {}) if p.is_file() else None


def lock(project: Any) -> list[str]:
    """Brownfield, a person: record the sha256 of principles V–VIII as they stand in the ratified constitution."""
    from .ratchet import actor
    import datetime
    if not project.is_brownfield:
        raise EkitError("`ekit constitution lock` is for adopted (brownfield) projects; in a greenfield project "
                        "principles I–VIII must match the kit template.")
    state, details = principles_drift(project, ignore_lock=True)
    mem = project.root / MEMORY
    if state == "missing":
        raise EkitError(details[0])
    have = principles(mem.read_text(encoding="utf-8"))
    want = principles(template_path(project).read_text(encoding="utf-8"))
    bad = [n for n in ROMAN if n not in TEAM and have.get(n) != want.get(n)]
    if bad:
        raise EkitError(f"principle(s) {', '.join(bad)} differ from the kit template; I–IV cannot be locked. "
                        f"Restore them first (`ekit constitution check`).")
    absent = [n for n in TEAM if n not in have]
    if absent:
        raise EkitError(f"principle(s) {', '.join(absent)} are missing from {MEMORY}; nothing to lock.")
    data = {"principles": {n: _sha(have[n]) for n in TEAM},
            "by": actor(project.root),
            "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    dump_yaml(data, project.root / LOCK)
    differing = [n for n in TEAM if have[n] != want.get(n)]
    return [f"locked principles {', '.join(TEAM)} in {LOCK}"
            + (f" ({', '.join(differing)} differ from the kit template: your team's text is now the reference)"
               if differing else " (they equal the kit template)")]


def principles_drift(project: Any, *, ignore_lock: bool = False) -> tuple[str, list[str]]:
    """('missing' | 'unratified' | 'changed' | 'intact', details).

    I–IV always match the kit template. V–VIII match the template too, except in a brownfield project
    with `.ekit/constitution.lock.yaml`: then they match the lock (0.6.0)."""
    mem = project.root / MEMORY
    if not mem.is_file():
        return "missing", [f"{MEMORY} does not exist (`ekit constitution ratify` creates and ratifies it)"]
    text = mem.read_text(encoding="utf-8")
    want = principles(template_path(project).read_text(encoding="utf-8"))
    have = principles(text)
    brown = bool(getattr(project, "is_brownfield", False))
    lk = read_lock(project.root) if (brown and not ignore_lock) else None
    locked = (lk or {}).get("principles") or {}
    changed = []
    for n in ROMAN:
        if n not in want:
            continue
        if lk is not None and n in TEAM:
            if n not in have:
                changed.append(f"principle {n} is missing")
            elif locked.get(n) != _sha(have[n]):
                changed.append(f"principle {n} differs from {LOCK} (a person re-runs `ekit constitution lock` "
                               "if the team changed it on purpose)")
        elif have.get(n) != want[n]:
            hint = ""
            if brown and n in TEAM:
                hint = " (to adopt your team's principles V–VIII a person runs `ekit constitution lock`)"
            changed.append(f"principle {n} {'is missing' if n not in have else 'differs from the kit template'}{hint}")
    if changed:
        return "changed", changed
    if placeholders(text):
        return "unratified", [f"placeholders left: {', '.join(placeholders(text))} (run `ekit constitution ratify`)"]
    return "intact", []
