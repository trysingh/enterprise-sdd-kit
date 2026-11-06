"""ekit 0.7.0: a Given step that describes a fault/outage but never wires one into the app.

Real bug: `ctx.remember("client_list_unavailable", True)` with nothing reading that flag has no
effect on the request path, so a scenario built to exercise error-handling behaviour doesn't.
Caught statically at red (`bdd.vacuous_steps` / `RED-STEPS-ASSERT`), as a warning, before freeze.
"""
from __future__ import annotations

from ekit import stepscan

UNWIRED = '''
from pytest_bdd import given

@given("the client list is unavailable")
def client_list_is_unavailable(ctx):
    ctx.remember("client_list_unavailable", True)
'''

WIRED = '''
from pytest_bdd import given

@given("the client list is unavailable")
def client_list_is_unavailable(ctx):
    ctx.client.app.dependency_overrides[get_client_list] = lambda: _raise()
    ctx.remember("client_list_unavailable", True)
'''

ORDINARY_BUSINESS_STEP = '''
from pytest_bdd import given

@given("Alice is signed in without access to Northwind")
def alice_without_access(ctx):
    ctx.remember("user", create_client("alice"))
'''

ALLOWED = '''
from pytest_bdd import given

@given("the client list is unavailable")
def client_list_is_unavailable(ctx):  # ekit: allow-unwired-fault flag checked by a later step's stub
    ctx.remember("client_list_unavailable", True)
'''

WHEN_STEP_SAME_WORDING = '''
from pytest_bdd import when

@when("the client list is unavailable")
def client_list_is_unavailable(ctx):
    ctx.remember("client_list_unavailable", True)
'''

THEN_STEP_SAME_WORDING = '''
from pytest_bdd import then

@then("the client list is unavailable")
def client_list_is_unavailable(ctx):
    ctx.remember("client_list_unavailable", True)
'''


def test_unwired_fault_step_is_flagged():
    res = stepscan.scan_source(UNWIRED)
    assert not res.steps                          # not vacuous: it does call ctx.remember
    assert [i.name for i in res.fault_steps] == ["client_list_is_unavailable"]
    assert "the client list is unavailable" in res.fault_steps[0].reason
    assert "dependency_overrides" in res.fault_steps[0].reason


def test_wired_fault_step_is_not_flagged():
    res = stepscan.scan_source(WIRED)
    assert not res.fault_steps


def test_ordinary_business_wording_is_not_flagged():
    """A Given with no infrastructure/outage vocabulary, that also only calls ctx.remember, is a
    real no-fault-injection step, not a bug: the vocabulary is deliberately narrower than
    business-rule-denial wording."""
    res = stepscan.scan_source(ORDINARY_BUSINESS_STEP)
    assert not res.fault_steps
    assert not res.steps


def test_allow_fault_marker_suppresses_the_warning():
    res = stepscan.scan_source(ALLOWED)
    assert not res.fault_steps


def test_when_and_then_steps_are_not_scanned_for_fault_wiring():
    assert not stepscan.scan_source(WHEN_STEP_SAME_WORDING).fault_steps
    assert not stepscan.scan_source(THEN_STEP_SAME_WORDING).fault_steps
