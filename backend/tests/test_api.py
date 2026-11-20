import asyncio
import json
from fastapi.testclient import TestClient
from app.main import app
from app.log_recorder import FlightLogRecorder

client=TestClient(app)

def test_health_is_local_backend():
    r=client.get("/api/health")
    assert r.status_code==200
    assert r.json()["ok"] is True

def test_arm_requires_confirmation_and_link():
    r=client.post("/api/vehicle/arm",json={"confirm":False})
    assert r.status_code==400
    assert "confirmation" in r.text.lower()

def test_raw_command_endpoint_is_disabled():
    r=client.post("/api/vehicle/command",json={"confirm":True})
    assert r.status_code==400
    assert "disabled" in r.text.lower()

def test_empty_mission_is_rejected():
    r=client.post("/api/vehicle/mission/upload",json={"items":[]})
    assert r.status_code==400

def test_calibration_without_vehicle_is_rejected():
    r=client.post("/api/vehicle/calibration/gyro",json={"confirm":True})
    assert r.status_code==400

def test_telemetry_recorder_writes_real_status(tmp_path):
    async def run():
        recorder=FlightLogRecorder(tmp_path)
        await recorder.start(lambda:{"connected":False,"telemetry":{}})
        await asyncio.sleep(1.05)
        result=await recorder.stop()
        return recorder,result
    recorder,result=asyncio.run(run())
    file=tmp_path/result["filename"]
    assert file.exists()
    line=json.loads(file.read_text().splitlines()[0])
    assert line["status"]["connected"] is False

def test_firmware_flash_requires_confirmation():
    r=client.post("/api/firmware/flash",json={"port":"COM5","filename":"not-downloaded.apj","confirm":False})
    assert r.status_code==400
    assert "confirmation" in r.text.lower()

def test_firmware_catalog_rejects_unknown_channel():
    r=client.get("/api/firmware/catalog?channel=bogus&variant=standard")
    assert r.status_code==400

def test_motor_test_rejected_without_ardupilot_vehicle():
    r=client.post("/api/vehicle/motor-test",json={"motor":1,"throttle_pct":5,"duration":1,"confirm":True})
    assert r.status_code==400
