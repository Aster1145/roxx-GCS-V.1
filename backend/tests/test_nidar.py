from fastapi.testclient import TestClient

from app import nidar
from app.main import app


def test_nidar_local_mission_flow(monkeypatch):
    monkeypatch.setattr(nidar, "bridge", nidar.Bridge())
    monkeypatch.setenv("NIDAR_BRIDGE_TOKEN", "test-only")
    client = TestClient(app)
    prefix = "/api/nidar"
    relay = {"X-Nidar-Token": "test-only"}
    operator = {"X-Nidar-Operator": "console"}
    point = {"x": 0, "y": 0}
    snapshot = {"mission_id": "run-1", "sequence": 1, "phase": "ready", "elapsed_s": 0,
                "grid_size_m": 1, "grid_origin": point, "entry_exit": point,
                "map": {"width": 2, "height": 2, "origin": point, "resolution_m": 0.5,
                        "cells": [-1, 0, 100, 0]}}
    assert not client.get(prefix + "/status").json()["link_live"]
    assert client.put(prefix + "/snapshot", json=snapshot).status_code == 401
    bad = {**snapshot, "map": {**snapshot["map"], "cells": [0]}}
    assert client.put(prefix + "/snapshot", json=bad, headers=relay).status_code == 422
    assert client.put(prefix + "/snapshot", json=snapshot, headers=relay).status_code == 200
    assert client.put(prefix + "/snapshot", json=snapshot, headers=relay).status_code == 409
    command_url = prefix + "/command/{}?mission_id=run-1"
    assert client.post(command_url.format("start")).status_code == 403
    started = client.post(command_url.format("start"), headers=operator)
    assert started.status_code == 202
    aborted = client.post(command_url.format("abort"), headers=operator)
    assert aborted.status_code == 202
    assert aborted.json()["id"] != started.json()["id"]
    snapshot.update(sequence=2, phase="aborted", acknowledged_command_id=aborted.json()["id"],
                    survivors=[{"id": "S1", "x": 0.5, "y": 0.5}])
    assert client.put(prefix + "/snapshot", json=snapshot, headers=relay).json()["pending_command"] is None
    camera_headers = {**relay, "Content-Type": "image/jpeg"}
    frame = b"\xff\xd8test\xff\xd9"
    assert client.put(prefix + "/camera/old-run", content=frame, headers=camera_headers).status_code == 409
    assert client.put(prefix + "/camera/run-1", content=frame, headers=camera_headers).status_code == 204
    assert client.get(prefix + "/camera").content == frame
    assert client.get(prefix + "/status").json()["snapshot"]["survivors"][0]["id"] == "S1"
    nidar.bridge.received_at -= 5
    assert not client.get(prefix + "/status").json()["link_live"]
