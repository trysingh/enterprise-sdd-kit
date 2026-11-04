"""Edit protection for the agent: ekit owns a set of `permission.edit` rules in opencode.json.

OpenCode refuses edit/write/patch tool calls to paths a rule marks "deny". ekit uses that to
  * always protect its own files and the agent wiring (.ekit/*, opencode.json, .opencode/*);
  * freeze a feature's .feature files and bound test modules once `ekit gate red` records them;
  * lift a freeze only through `ekit unfreeze <feature> --reason "..."`, which leaves an audit record.

State lives in `.ekit/freeze.yaml` (commit it); opencode.json is derived from it and re-synced by
ekit, so the user's own rules in opencode.json are kept. OpenCode applies "the last matching rule
wins", so ekit's deny rules are always written after the catch-all.

Limits, stated plainly: these rules cover the agent's edit tools. A shell command (`sed -i`, a script)
is not covered; `GREEN-TESTS-UNCHANGED` is the backstop that detects such a change. OpenCode may read its
config only at startup, so restart it after a freeze or unfreeze.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from .project import EkitError, dump_yaml, git, load_yaml

OPENCODE_JSON = "opencode.json"
SCHEMA = "https://opencode.ai/config.json"
ALWAYS = [".ekit/*", "opencode.json", ".opencode/*"]
# Decisions a person makes: denied to the agent's shell tool (`permission.bash`). Running them through
# another wrapper (`uv run ekit …`, a script) is not covered; the records they write name who acted.
ALWAYS_BASH = [
    "ekit unfreeze*",
    "ekit fix-red*",     # wraps unfreeze; same reason it's denied
    "ekit upgrade*",
    "ekit wave approve*",
    "ekit wave advance*",
    "ekit wave decline*",
    "ekit models*",
]


def state_path(root: Path) -> Path:
    return root / ".ekit" / "freeze.yaml"


def load_state(root: Path) -> dict[str, Any]:
    p = state_path(root)
    data = (load_yaml(p) or {}) if p.is_file() else {}
    data.setdefault("managed", [])
    data.setdefault("managed_bash", [])
    data.setdefault("frozen", {})
    data.setdefault("narrow", {})   # feature -> source-dir deny patterns, while its tests are unfrozen
    data.setdefault("history", [])
    return data


def desired_patterns(state: dict[str, Any]) -> list[str]:
    pats = list(ALWAYS)
    for feature_patterns in (state.get("frozen") or {}).values():
        pats += feature_patterns
    for narrow_patterns in (state.get("narrow") or {}).values():
        pats += narrow_patterns
    return list(dict.fromkeys(pats))


def patterns_for(feature: str, fingerprints: dict[str, str]) -> list[str]:
    """Feature files collapse to one directory pattern (so new files are covered); test modules stay exact."""
    prefix = f"specs/{feature}/features/"
    return sorted({prefix + "*" if rel.startswith(prefix) else rel for rel in fingerprints})


def source_dirs(project: Any) -> list[str]:
    """Each active profile's production source dir (profile.yaml's layout.source), as a plain
    relative directory path — the thing `ekit unfreeze` denies (as a glob) and `ekit fix-red`
    temporarily reverts."""
    dirs: list[str] = []
    for prof in getattr(project, "active_profiles", None) or project.profiles:
        src = (prof.data.get("layout") or {}).get("source")
        if not src:
            continue
        base = project.rel(prof.root)
        dirs.append(src if base in (".", "") else f"{base}/{src}")
    return sorted(set(dirs))


def source_patterns(project: Any) -> list[str]:
    """`source_dirs`, as `permission.edit` deny glob patterns."""
    return [f"{d}/**" for d in source_dirs(project)]


def _read_config(root: Path, rules_hint: list[str]) -> dict[str, Any]:
    p = root / OPENCODE_JSON
    if not p.is_file():
        return {"$schema": SCHEMA}
    hint = ("Add these to permission.edit yourself with the value \"deny\": " + ", ".join(rules_hint))
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise EkitError(f"{OPENCODE_JSON} is not strict JSON ({exc}), so ekit cannot edit it safely. {hint}") from None
    if not isinstance(data, dict):
        raise EkitError(f"{OPENCODE_JSON} must contain a JSON object. {hint}")
    return data


def sync_permissions(root: Path) -> list[str]:
    """Rewrite ekit's rules in opencode.json from .ekit/freeze.yaml; user rules are preserved."""
    if (root / "opencode.jsonc").is_file() and not (root / OPENCODE_JSON).is_file():
        raise EkitError("opencode.jsonc exists but ekit only manages opencode.json; rename it or add the deny rules by hand "
                        f"({', '.join(desired_patterns(load_state(root)))}).")
    state = load_state(root)
    desired = desired_patterns(state)
    data = _read_config(root, desired)
    perm = data.setdefault("permission", {})
    if not isinstance(perm, dict):
        raise EkitError(f"{OPENCODE_JSON}: `permission` must be an object.")
    edit = perm.get("edit")
    if edit is None:
        rules: dict[str, str] = {}
    elif isinstance(edit, str):
        rules = {"*": edit}
    elif isinstance(edit, dict):
        rules = dict(edit)
    else:
        raise EkitError(f"{OPENCODE_JSON}: `permission.edit` must be a string or an object.")
    for old in state["managed"]:
        rules.pop(old, None)
    if "*" not in rules:
        rules = {"*": "allow", **rules}          # OpenCode's default for edit; keeps behaviour unchanged
    for pat in desired:
        rules.pop(pat, None)
        rules[pat] = "deny"                       # re-inserted last: the last matching rule wins
    perm["edit"] = rules
    bash = perm.get("bash")
    if bash is None:
        brules: dict[str, str] = {}
    elif isinstance(bash, str):
        brules = {"*": bash}
    elif isinstance(bash, dict):
        brules = dict(bash)
    else:
        raise EkitError(f"{OPENCODE_JSON}: `permission.bash` must be a string or an object.")
    for old_pat in state["managed_bash"]:
        brules.pop(old_pat, None)
    if "*" not in brules:
        brules = {"*": "allow", **brules}        # OpenCode's default for bash; keeps behaviour unchanged
    for pat in ALWAYS_BASH:
        brules.pop(pat, None)
        brules[pat] = "deny"                      # last matching rule wins
    perm["bash"] = brules
    (root / OPENCODE_JSON).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    state["managed"] = desired
    state["managed_bash"] = list(ALWAYS_BASH)
    dump_yaml(state, state_path(root))
    return desired


def freeze_feature(root: Path, feature: str, fingerprints: dict[str, str]) -> list[str]:
    state = load_state(root)
    state["frozen"][feature] = patterns_for(feature, fingerprints)
    state["narrow"].pop(feature, None)   # re-frozen: the narrow source-edit protection is no longer needed
    dump_yaml(state, state_path(root))
    return sync_permissions(root)


def freeze_from_ledger(root: Path, feature: str) -> list[str]:
    ledger = root / ".ekit" / "ledger" / f"{feature}.yaml"
    if not ledger.is_file():
        raise EkitError(f"No ledger for {feature}: run `ekit gate red` first.")
    reds = [e for e in ((load_yaml(ledger) or {}).get("entries") or []) if e.get("phase") == "red" and e.get("fingerprints")]
    if not reds:
        raise EkitError(f"The red entry for {feature} has no fingerprints (older ekit): re-run `ekit gate red` while the code is still red.")
    return freeze_feature(root, feature, reds[-1]["fingerprints"])


def _who(root: Path) -> str:
    return git(root, "config", "user.email") or git(root, "config", "user.name") or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def unfreeze_feature(root: Path, feature: str, reason: str, *, narrow_src: list[str] | None = None) -> list[str]:
    """Lift the test freeze. By default (narrow_src given) this also denies the feature's own
    production source directories for as long as it stays unfrozen: the point of unfreezing is to
    fix the test, and an agent that uses the window to implement production code instead has, in
    practice, repeated the mistake this exists to catch. `ekit gate red` lifts the source-deny again
    the moment it re-freezes. Pass narrow_src=None (or `--allow-src` on the CLI) to skip this."""
    if not reason.strip():
        raise EkitError("A reason is required: ekit unfreeze <feature> --reason \"...\"")
    state = load_state(root)
    if feature not in state["frozen"]:
        raise EkitError(f"{feature} is not frozen.")
    paths = state["frozen"].pop(feature)
    if narrow_src:
        state["narrow"][feature] = sorted(set(narrow_src))
    else:
        state["narrow"].pop(feature, None)
    state["history"].append({
        "action": "unfreeze", "feature": feature, "reason": reason.strip(), "by": _who(root),
        "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), "paths": paths,
        "narrowed_source": state["narrow"].get(feature) or [],
    })
    dump_yaml(state, state_path(root))
    return sync_permissions(root)


def verify(root: Path) -> list[tuple[bool, str, str]]:
    """Rows for `ekit doctor`: (ok, label, detail)."""
    state = load_state(root)
    p = root / OPENCODE_JSON
    if not p.is_file():
        return [(False, "opencode.json edit rules", "missing: run `ekit sync`")]
    try:
        edit = ((json.loads(p.read_text(encoding="utf-8-sig")).get("permission") or {}).get("edit"))
    except (json.JSONDecodeError, AttributeError):
        return [(False, "opencode.json edit rules", "not strict JSON: ekit cannot verify or maintain it")]
    rules = edit if isinstance(edit, dict) else {}
    rows: list[tuple[bool, str, str]] = []
    missing = [pat for pat in ALWAYS if rules.get(pat) != "deny"]
    rows.append((not missing, "agent cannot edit ekit/OpenCode wiring", ", ".join(ALWAYS) if not missing else f"missing deny for {', '.join(missing)}: run `ekit sync`"))
    brules = ((json.loads(p.read_text(encoding="utf-8-sig")).get("permission") or {}).get("bash"))
    brules = brules if isinstance(brules, dict) else {}
    bmissing = [pat for pat in ALWAYS_BASH if brules.get(pat) != "deny"]
    rows.append((not bmissing, "agent cannot run approval commands",
                 "ekit unfreeze / fix-red / upgrade / wave approve|advance|decline / models" if not bmissing
                 else f"missing bash deny for {', '.join(bmissing)}: run `ekit sync`"))
    for feature, pats in sorted(state["frozen"].items()):
        gone = [x for x in pats if rules.get(x) != "deny"]
        rows.append((not gone, f"{feature} frozen", f"{len(pats)} rule(s)" if not gone else f"missing deny for {', '.join(gone)}: run `ekit freeze {feature}`"))
    for feature, pats in sorted((state.get("narrow") or {}).items()):
        gone = [x for x in pats if rules.get(x) != "deny"]
        rows.append((not gone, f"{feature} unfrozen (source protected)",
                     f"production source denied while fixing the test: {', '.join(pats)}" if not gone
                     else f"missing deny for {', '.join(gone)}: run `ekit sync`"))
    return rows
