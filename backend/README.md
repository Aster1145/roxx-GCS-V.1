# ROXX GCS Backend
Real MAVLink backend (no generated flight telemetry).

## Setup
Python 3.10+ recommended.
```powershell
cd backend
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

## Connect
- Serial: COM5 or /dev/ttyACM0 (baud is configurable)
- UDP: udp:127.0.0.1:14550
- TCP: tcp:127.0.0.1:5760

The backend waits for an actual MAVLink heartbeat. No heartbeat means connection fails. This is not a simulated vehicle.

## Firmware updates
The firmware module is targeted to **Matek H743-MINI V3 / ArduCopter / MatekH743**. Firmware downloads are fetched from the official ArduPilot firmware server. APJ images are validated and cached before upload. APJ flashing uses the vendored upstream ArduPilot uploader, which checks the bootloader board ID and will not force a mismatch. Flash requires the MAVLink transport closed and explicit UI/API confirmation. The initial DFU HEX can be downloaded, but DFU writing is done with STM32CubeProgrammer separately.

## Optional MAVSDK telemetry (ArduPilot SITL)

From `backend/`, install `python -m pip install -r requirements-mavsdk.txt` and
start `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
Use Python 3.11+ on a platform supported by the pinned MAVSDK wheel.

Configure your SITL MAVLink output to send to `127.0.0.1:14540` (for
MAVProxy, add `--out=udp:127.0.0.1:14540`). If you also use the original
pymavlink connection, keep it on a separate SITL output, e.g. port `14550`.

```sh
curl -X POST http://127.0.0.1:8000/api/mavsdk/connect \
  -H 'Content-Type: application/json' -d '{"port":14540}'
curl http://127.0.0.1:8000/api/mavsdk/status
curl -X POST http://127.0.0.1:8000/api/mavsdk/disconnect
```

Connect returns `202` while waiting up to 10 seconds for an autopilot. Poll
status for the connection state and latest position, attitude, battery, armed
state, and flight mode as SITL publishes them. Telemetry is empty while
unconnected. MAVSDK listens on loopback and exposes telemetry only; the existing
frontend, `/ws/telemetry`, and vehicle control API still use pymavlink. The
optional UDP smoke test uses generated ArduPilot-style MAVLink packets, not a
full SITL instance.
