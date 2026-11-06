"""Rigor levels (0.7.0): which checks run at which wave.

Rigor is a property of the wave (`rigor:` in `.ekit/waves.yaml`), described by
`policy/rigor.policy.yaml`. With no wave plan, or a current wave without `rigor:`, `level()` is None
and the gate engine behaves exactly as in 0.6.4.
"""
from __future__ import annotations

from typing import Any

from .project import EkitError, load_yaml


def load_policy(kit: Any) -> dict[str, Any]:
    try:
        path = kit.component("rigor_policy")
    except EkitError:
        return {}
    return (load_yaml(path) or {}) if path.is_file() else {}


def levels(kit: Any) -> list[str]:
    return list((load_policy(kit).get("levels") or {}))


def level(project: Any) -> str | None:
    """Rigor level of the current wave, or None when not configured."""
    plan = getattr(project, "wave_plan", None)
    if plan is None or not plan.current:
        return None
    try:
        lv = plan.wave(plan.current).get("rigor")
    except EkitError:
        return None
    return str(lv) if lv else None


def _key(spec: dict[Any, Any], name: str) -> Any:
    """`on` / `off` are booleans when a policy author forgets the quotes (YAML 1.1); accept both."""
    return spec.get(name, spec.get(name == "on"))


def _names(policy: dict[str, Any], gate_id: str, check_id: str) -> tuple[set[str], set[str]]:
    own = {check_id}
    for alias, ids in (policy.get("aliases") or {}).items():
        if check_id in (ids or []):
            own.add(str(alias))
    return own, own | {gate_id}


def addon_checks(policy: dict[str, Any]) -> set[str]:
    return {str(c) for lv in (policy.get("levels") or {}).values() for c in (lv or {}).get("add") or []}


def decide(policy: dict[str, Any], lv: str | None, gate_id: str, check_id: str) -> str | None:
    """None: the check runs. 'omit': it is not part of this configuration at all. Else: why it is skipped."""
    addons = addon_checks(policy)
    if lv is None:
        return "omit" if check_id in addons else None
    spec = (policy.get("levels") or {}).get(lv)
    if spec is None:
        return None
    if check_id in addons and check_id not in {str(c) for c in spec.get("add") or []}:
        where = ", ".join(n for n, s in policy["levels"].items() if check_id in (s or {}).get("add", []))
        return f"rigor {lv}: only runs at {where}"
    own, with_gate = _names(policy, gate_id, check_id)
    on = _key(spec, "on")
    if isinstance(on, list) and own & {str(x) for x in on}:
        return None
    off = _key(spec, "off") or []
    offs = {str(x) for x in off}
    hit = sorted(own & offs) or sorted(with_gate & offs)      # the most specific name that switched it off
    if hit:
        return f"rigor {lv}: '{hit[0]}' is off at this level"
    return None
