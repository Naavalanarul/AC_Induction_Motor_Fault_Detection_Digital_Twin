"""Regression for bug 1: every fault type the UI offers must be injectable through the API.

The frontend list (frontend/src/api/types.ts FAULT_TYPES) is parsed directly so the two cannot
drift apart again: 7 of its 16 entries used to be diagnosis-only labels that returned HTTP 422.
"""

import re
from pathlib import Path

import pytest

from app.simulation.faults import FaultType

FRONTEND_TYPES = Path(__file__).resolve().parents[4] / "frontend" / "src" / "api" / "types.ts"


def frontend_fault_types() -> list[str]:
    src = FRONTEND_TYPES.read_text()
    block = re.search(r"export const FAULT_TYPES = \[(.*?)\] as const", src, re.S)
    assert block, "FAULT_TYPES not found in frontend/src/api/types.ts"
    return re.findall(r"'([a-z_]+)'", block.group(1))


def test_frontend_list_equals_backend_enum():
    assert sorted(frontend_fault_types()) == sorted(f.value for f in FaultType)


@pytest.mark.parametrize("fault_type", frontend_fault_types())
def test_every_ui_fault_type_is_accepted(client, auth, fault_type):
    params = {"interturn_short": {"phase": "a"}, "broken_rotor_bar": {"count": 1}}.get(fault_type, {})
    r = client.post("/api/v1/motors/1/faults", json={"fault_type": fault_type, "severity": 0.2, "params": params},
                    headers=auth("operator"))
    assert r.status_code == 201, r.text
    assert client.delete(f"/api/v1/motors/1/faults/{r.json()['id']}", headers=auth("operator")).status_code == 200


@pytest.mark.parametrize("alias,kind", [("voltage_sag", "sag"), ("supply_anomaly", "imbalance")])
def test_supply_aliases_map_to_voltage_anomaly(client, auth, alias, kind):
    r = client.post("/api/v1/motors/1/faults", json={"fault_type": alias, "severity": 0.2}, headers=auth("operator"))
    assert r.status_code == 201, r.text
    assert r.json()["fault_type"] == "voltage_anomaly" and r.json()["params_json"]["type"] == kind
    client.delete(f"/api/v1/motors/1/faults/{r.json()['id']}", headers=auth("operator"))


@pytest.mark.parametrize("label", ["overheating", "overload", "overcurrent", "stall", "phase_loss"])
def test_diagnosis_only_labels_rejected_with_explanation(client, auth, label):
    r = client.post("/api/v1/motors/1/faults", json={"fault_type": label, "severity": 0.2}, headers=auth("operator"))
    assert r.status_code == 422
    assert "diagnosis label, not an injectable fault" in r.text
