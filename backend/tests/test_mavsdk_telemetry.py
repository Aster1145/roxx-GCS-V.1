import socket
import time

import pytest
from fastapi.testclient import TestClient
from pymavlink import mavutil

from app.main import app, mavsdk_telemetry
from app.mavsdk_telemetry import finite_fields


def test_optional_dependency(monkeypatch):
    def missing():
        raise ModuleNotFoundError("mavsdk")

    monkeypatch.setattr(mavsdk_telemetry, "_loader", missing)
    with TestClient(app) as client:
        assert client.post("/api/mavsdk/connect", json={"port": 0}).status_code == 422
        assert client.post("/api/mavsdk/connect", json={}).status_code == 503
        assert client.get("/api/mavsdk/status").json()["state"] == "idle"


def test_nonfinite_telemetry_is_json_safe():
    from types import SimpleNamespace

    assert finite_fields(SimpleNamespace(roll_deg=float("nan")), "roll_deg") == {"roll_deg": None}


def test_mavsdk_receives_ardupilot_style_udp_telemetry():
    pytest.importorskip("mavsdk")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    link = mavutil.mavlink_connection(f"udpout:127.0.0.1:{port}", source_system=1, source_component=1)
    try:
        with TestClient(app) as client:
            assert client.post("/api/mavsdk/connect", json={"port": port}).status_code == 202
            assert client.post("/api/mavsdk/connect", json={"port": port}).status_code == 409
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                link.mav.heartbeat_send(2, 3, 1, 0, 4)
                link.mav.global_position_int_send(100, 129716000, 775946000, 900000, 20000, 0, 0, 0, 0)
                status = client.get("/api/mavsdk/status").json()
                if status["connected"] and "position" in status["telemetry"]:
                    break
                assert status["state"] != "error", status
                time.sleep(0.1)
            else:
                pytest.fail(f"No MAVSDK position received: {status}")
            assert status["system_id"] == 1
            assert status["telemetry"]["position"]["relative_altitude_m"] == pytest.approx(20)
            assert not client.get("/api/vehicle/status").json()["connected"]
            assert client.post("/api/mavsdk/disconnect").json()["state"] == "idle"
    finally:
        link.close()
