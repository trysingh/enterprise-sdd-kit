"""Optional model routing: run each OpenCode command and kit agent on a model tier.

The kit (pinned) maps commands and agents to tiers in `policy/models.policy.yaml`.
The project maps tiers to models in `.ekit/models.yaml` (`ekit models setup`; agents cannot run it).
ekit writes the result into the frontmatter of the OpenCode command and agent files, which OpenCode
reads as a per-command / per-agent model override, and adds a banner so the agent states its tier
and configured model at the start of every routed command.

What ekit can and cannot know: it records the model it CONFIGURED. A developer can still pick another
model in the OpenCode UI, so ledger entries say `model_configured`, never "the model that ran".
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project import EkitError, dump_yaml, load_yaml

CONFIG = ".ekit/models.yaml"
APPLIED = ".ekit/models.applied.yaml"
MARK = "# ekit-model"
BANNER_BEGIN = "<!-- ekit:model -->"
BANNER_END = "<!-- /ekit:model -->"
COMMAND_DIRS = (".opencode/commands", ".opencode/command")   # newer and older OpenCode layouts
AGENT_DIRS = (".opencode/agents", ".opencode/agent")
FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?\r?\n)?---[ \t]*(\r?\n|\Z)", re.S)


# --------------------------------------------------------------------------- policy and config
def policy(kit: Any) -> dict[str, Any]:
    try:
        return load_yaml(kit.component("models_policy")) or {}
    except EkitError:
        return {}


def load_config(root: Path) -> dict[str, Any] | None:
    p = root / CONFIG
    if not p.is_file():
        return None
    data = load_yaml(p) or {}
    if not isinstance(data, dict):
        raise EkitError(f"{CONFIG} must be a mapping with `tiers:`.")
    return data


def valid_overrides(config: dict[str, Any], tiers: list[str]) -> tuple[dict[str, str], list[str]]:
    """Same rules as policy overrides: reason, approved_by and an unexpired `expires`, else ignored and reported."""
    out: dict[str, str] = {}
    notes: list[str] = []
    today = dt.date.today()
    for name, ov in (config.get("overrides") or {}).items():
        if not isinstance(ov, dict):
            notes.append(f"model override for {name} ignored: must be a mapping with tier, reason, approved_by, expires")
            continue
        missing = [k for k in ("tier", "reason", "approved_by", "expires") if not str(ov.get(k) or "").strip()]
        if missing:
            notes.append(f"model override for {name} ignored: {', '.join('`' + k + '`' for k in missing)} required")
            continue
        if str(ov["tier"]) not in tiers:
            notes.append(f"model override for {name} ignored: unknown tier {ov['tier']}")
            continue
        exp = ov["expires"]
        try:
            exp_d = exp if isinstance(exp, dt.date) else dt.date.fromisoformat(str(exp))
        except ValueError:
            notes.append(f"model override for {name}: bad expires date '{exp}'; ignored")
            continue
        if exp_d < today:
            notes.append(f"model override for {name} expired on {exp_d}; ignored")
            continue
        out[str(name)] = str(ov["tier"])
    return out, notes


@dataclass
class Route:
    name: str
    kind: str          # command | agent
    tier: str
    model: str | None
    overridden: bool = False


def routes(root: Path, kit: Any) -> tuple[list[Route], list[str]]:
    """Effective routing. Empty when model routing is off."""
    config = load_config(root)
    if config is None:
        return [], []
    pol = policy(kit)
    tiers = [str(t) for t in pol.get("tiers") or ["flagship", "standard", "light"]]
    models = {t: str(((config.get("tiers") or {}).get(t) or {}).get("model") or "").strip() or None for t in tiers}
    overrides, notes = valid_overrides(config, tiers)
    out: list[Route] = []
    for kind, table in (("command", pol.get("commands") or {}), ("agent", pol.get("agents") or {})):
        for name, tier in table.items():
            t = overrides.get(name, str(tier))
            out.append(Route(str(name), kind, t, models.get(t), name in overrides))
    for t, m in models.items():
        if m is None and any(r.tier == t for r in out):
            notes.append(f"tier {t} has no model in {CONFIG}; its commands keep the session's default model")
    return out, notes


def small_model(root: Path, kit: Any) -> str | None:
    config = load_config(root)
    if config is None:
        return None
    tier = str(policy(kit).get("small_model") or "")
    return str(((config.get("tiers") or {}).get(tier) or {}).get("model") or "").strip() or None


# --------------------------------------------------------------------------- files
def _md_files(root: Path, dirs: tuple[str, ...]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in dirs:
        base = root / d
        if base.is_dir():
            for f in sorted(base.glob("*.md")):
                found.setdefault(f.stem, f)
    return found


def command_files(root: Path) -> dict[str, Path]:
    return _md_files(root, COMMAND_DIRS)


def agent_files(root: Path) -> dict[str, Path]:
    return _md_files(root, AGENT_DIRS)


def strip_routing(text: str, original: str | None = None) -> str:
    """Remove what ekit added: the marked `model:` line (restoring `original` if one was replaced) and the banner."""
    text = re.sub(re.escape(BANNER_BEGIN) + r".*?" + re.escape(BANNER_END) + r"\r?\n?", "", text, flags=re.S)
    m = FRONTMATTER_RE.match(text)
    if not m:
        return text
    body = m.group(1) or ""
    lines = [ln for ln in body.splitlines(keepends=True) if not (ln.lstrip().startswith("model:") and MARK in ln)]
    if original and not any(ln.lstrip().startswith("model:") for ln in lines):
        lines.append(f"model: {original}\n")
    if not lines:
        return text[m.end():]
    return "---\n" + "".join(lines) + "---\n" + text[m.end():]


def with_routing(text: str, model: str, tier: str) -> tuple[str, str | None]:
    """Set `model:` in the frontmatter (marked as ekit's) and add the banner. Returns (text, replaced original)."""
    m = FRONTMATTER_RE.match(text)
    original = None
    if m:
        body = m.group(1) or ""
        kept = []
        for ln in body.splitlines(keepends=True):
            if ln.lstrip().startswith("model:"):
                if MARK not in ln:
                    original = ln.split(":", 1)[1].strip().strip("'\"") or None
                continue
            kept.append(ln)
        rest = text[m.end():]
    else:
        kept, rest = [], text
    kept.append(f"model: {model}  {MARK}\n")
    banner = (f"{BANNER_BEGIN}\n"
              f"> **Model routing (ekit):** this command runs on the **{tier}** tier, configured model `{model}`. "
              f"Begin your first reply with exactly this line: `[ekit] tier: {tier} · model: {model}`\n"
              f"{BANNER_END}\n")
    rest = re.sub(re.escape(BANNER_BEGIN) + r".*?" + re.escape(BANNER_END) + r"\r?\n?", "", rest, flags=re.S)
    return "---\n" + "".join(kept) + "---\n" + banner + rest, original


# --------------------------------------------------------------------------- apply / remove
def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # tolerate // comments in a global opencode.jsonc for discovery only
        try:
            data = json.loads(re.sub(r"(?m)^\s*//.*$", "", raw))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def apply(root: Path, kit: Any) -> list[str]:
    """Write routing into command/agent files and opencode.json. Idempotent; reverses itself first."""
    remove(root, quiet=True)
    rts, notes = routes(root, kit)
    if not rts:
        return notes
    cmds, agents = command_files(root), agent_files(root)
    applied: dict[str, Any] = {"files": {}, "small_model": None}
    written = 0
    for r in rts:
        f = (cmds if r.kind == "command" else agents).get(r.name)
        if f is None or not r.model:
            continue
        text, original = with_routing(f.read_text(encoding="utf-8"), r.model, r.tier)
        f.write_text(text, encoding="utf-8", newline="\n")
        applied["files"][f.relative_to(root).as_posix()] = {"tier": r.tier, "model": r.model, "original": original}
        written += 1
    sm = small_model(root, kit)
    if sm:
        oc = root / "opencode.json"
        data = _read_json(oc) if oc.is_file() else {"$schema": "https://opencode.ai/config.json"}
        if data is None:
            notes.append("opencode.json is not strict JSON: small_model not set")
        else:
            applied["small_model"] = {"value": sm, "previous": data.get("small_model")}
            data["small_model"] = sm
            oc.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    dump_yaml(applied, root / APPLIED)
    found = sum(1 for r in rts if (cmds if r.kind == "command" else agents).get(r.name))
    if found == 0:
        notes.append("no OpenCode command or agent files found under .opencode/: run `ekit sync` first")
    notes.insert(0, f"model routing applied to {written} command/agent file(s)")
    return notes


def remove(root: Path, quiet: bool = False) -> list[str]:
    p = root / APPLIED
    if not p.is_file():
        return [] if quiet else ["model routing was not applied"]
    applied = load_yaml(p) or {}
    n = 0
    for rel, info in (applied.get("files") or {}).items():
        f = root / rel
        if f.is_file():
            f.write_text(strip_routing(f.read_text(encoding="utf-8"), (info or {}).get("original")),
                         encoding="utf-8", newline="\n")
            n += 1
    sm = applied.get("small_model")
    oc = root / "opencode.json"
    if sm and oc.is_file():
        data = _read_json(oc)
        if data is not None and data.get("small_model") == sm.get("value"):
            if sm.get("previous"):
                data["small_model"] = sm["previous"]
            else:
                data.pop("small_model", None)
            oc.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    p.unlink()
    return [f"model routing removed from {n} file(s)"]


# --------------------------------------------------------------------------- discovery and setup
def _global_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "opencode"


def discover(root: Path) -> list[dict[str, Any]]:
    """Models configured in OpenCode (project, then global): id, known context window, where it was found."""
    seen: dict[str, dict[str, Any]] = {}
    sources = [(root / "opencode.json", "project"), (_global_config_dir() / "opencode.json", "global"),
               (_global_config_dir() / "opencode.jsonc", "global")]
    for path, where in sources:
        data = _read_json(path)
        if not data:
            continue
        for pid, prov in (data.get("provider") or {}).items():
            for mid, spec in ((prov or {}).get("models") or {}).items():
                ctx = ((spec or {}).get("limit") or {}).get("context") if isinstance(spec, dict) else None
                seen.setdefault(f"{pid}/{mid}", {"id": f"{pid}/{mid}", "context": ctx, "source": where, "role": ""})
        for key in ("model", "small_model"):
            v = data.get(key)
            if isinstance(v, str) and v:
                rec = seen.setdefault(v, {"id": v, "context": None, "source": where, "role": ""})
                rec["role"] = rec["role"] or key
    return list(seen.values())


def recommend(found: list[dict[str, Any]]) -> dict[str, str | None]:
    """A starting point only: largest known context for flagship, OpenCode's `model` for standard,
    its `small_model` (or standard) for light. The person decides."""
    by_role = {m["role"]: m["id"] for m in found if m.get("role")}
    sized = sorted((m for m in found if m.get("context")), key=lambda m: -int(m["context"]))
    standard = by_role.get("model") or (found[0]["id"] if found else None)
    flagship = sized[0]["id"] if sized else standard
    light = by_role.get("small_model") or standard
    return {"flagship": flagship, "standard": standard, "light": light}


def write_config(root: Path, tiers: dict[str, str | None]) -> Path:
    config = load_config(root) or {"apiVersion": "ekit/v1", "kind": "ModelRouting", "overrides": {}}
    config.setdefault("tiers", {})
    for tier, model in tiers.items():
        if model:
            config["tiers"].setdefault(tier, {})
            config["tiers"][tier]["model"] = model
    config.setdefault("overrides", {})
    config["updated_on"] = dt.date.today().isoformat()
    dump_yaml(config, root / CONFIG)
    return root / CONFIG


def off(root: Path) -> list[str]:
    notes = remove(root)
    if (root / CONFIG).is_file():
        (root / CONFIG).unlink()
        notes.append(f"deleted {CONFIG}: every command uses the session's default model again")
    return notes


# --------------------------------------------------------------------------- evidence and doctor
def ledger_fields(root: Path, kit: Any, command: str) -> dict[str, Any]:
    """What the ledger records about the model for a red/green entry (configured, not proven)."""
    try:
        rts, _ = routes(root, kit)
    except Exception:  # noqa: BLE001 - evidence must never break a gate
        return {}
    if not rts:
        return {"model_configured": "session default (model routing off)"}
    r = next((x for x in rts if x.name == command), None)
    if r is None:
        return {"model_configured": "session default (command not routed)"}
    return {"model_tier": r.tier, "model_configured": r.model or "session default (tier has no model)"}


def doctor_rows(root: Path, kit: Any) -> list[tuple[bool, str, str]]:
    if load_config(root) is None:
        return [(True, "model routing", "off (optional): `ekit models setup` to route commands by tier")]
    rows: list[tuple[bool, str, str]] = []
    rts, notes = routes(root, kit)
    cmds, agents = command_files(root), agent_files(root)
    found = [r for r in rts if (cmds if r.kind == "command" else agents).get(r.name)]
    if not found:
        rows.append((False, "model routing", "no routed command files found under .opencode/: run `ekit sync`"))
    stale = []
    for r in found:
        if not r.model:
            continue
        f = (cmds if r.kind == "command" else agents)[r.name]
        text = f.read_text(encoding="utf-8")
        if f"model: {r.model}  {MARK}" not in text:
            stale.append(r.name)
    rows.append((not stale, "model routing in command/agent files",
                 f"{len(found)} routed" if not stale else f"missing or outdated in {', '.join(stale)}: run `ekit sync` "
                 "(Spec Kit rewrites command files on upgrade)"))
    pol = policy(kit)
    known = {m["id"]: m for m in discover(root)}
    for tier, minimum in (pol.get("min_context") or {}).items():
        model = str((((load_config(root) or {}).get("tiers") or {}).get(tier) or {}).get("model") or "")
        if not model:
            continue
        ctx = (known.get(model) or {}).get("context")
        if ctx is None:
            rows.append((True, f"{tier} context window", f"{model}: unknown (set provider…models…limit.context in opencode.json to check)"))
        else:
            rows.append((int(ctx) >= int(minimum), f"{tier} context window",
                         f"{model}: {ctx} tokens" + ("" if int(ctx) >= int(minimum) else f" < recommended {minimum}")))
    for n in notes:
        rows.append((True, "model routing note", n))
    return rows
