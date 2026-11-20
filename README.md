# ROXX GCS — Team ROXX Ground Control Station

A ground-control application being built for Team ROXX. Target FC: Matek H743-MINI V3; autopilot: ArduPilot Copter. This repository is now an **actual MAVLink client**, not a fake telemetry demo. The frontend connects to a local FastAPI service; the backend opens a serial/UDP/TCP MAVLink link and requires a vehicle heartbeat. It does not generate aircraft telemetry.

## Current implementation
- Real MAVLink connection manager (serial endpoints and MAVLink UDP/TCP URIs)
- Heartbeat and vehicle identification, mode and arming state
- Live telemetry: GPS, global position, altitude, speed, attitude, battery and system status
- Flight mode selection using modes reported by the connected vehicle, plus ArduCopter FLTMODE1–6 slot configuration
- RC channel monitor, frame class/type configuration, guarded low-throttle motor test and ESC-calibration request
- MAVLink parameter list request, parameter cache, parameter write while disarmed, JSON backup/restore
- Sensor calibration command requests (gyro, accelerometer, compass, pressure, radio and airspeed)
- Confirmed arm/disarm, takeoff (GPS 3D fix required), land and RTL controls
- Interactive OpenStreetMap mission editor: add route points, edit altitude/type, upload/download mission, import/export JSON
- Live system events and autopilot STATUSTEXT feed
- Local telemetry recording to JSONL with start/stop/list/download
- Board-specific firmware catalog/download and guarded APJ flashing for Matek H743 Mini V3 (ArduCopter target), with board-ID validation and erase/program/verify status
- HEX download for initial DFU, with external STM32CubeProgrammer required
- Checklist for vehicle setup and preflight

## Current limitations (do not treat as finished flight software)
- Board-specific firmware download and APJ flash is implemented for Matek H743 Mini V3 ArduCopter, using the upstream ArduPilot uploader and board-ID matching. Initial DFU flashing (HEX) is downloadable but still uses STM32CubeProgrammer externally.
- Motor test is deliberately limited (ArduPilot only, disarmed, max 10% throttle/2 seconds); full motor order/servo output test wizard is not implemented.
- Mission download editor currently imports coordinate-based navigation commands (waypoint/takeoff/land) into the map; other mission command types are not yet editable in the map editor.
- Calibration requests are sent; interactive calibration progress and all autopilot-specific workflows still need validation.
- Flight/calibration command ACKs are awaited up to 3 seconds; parameter writes remain asynchronous with read-back requested. Verify critical values and vehicle behavior.
- Do not use for flight until validated in the correct SITL, bench/hardware-in-loop and controlled test process.

## Run on Windows (PowerShell)

### 1. Frontend
```powershell
git clone https://github.com/dhruvatr/roxx-GCS.git
cd roxx-GCS\frontend
npm install
npm run dev
```
Open the Vite URL (normally http://localhost:5173).

### 2. Backend (separate terminal)
```powershell
cd roxx-GCS\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
API documentation: http://127.0.0.1:8000/docs

## Connect
- Serial example: `COM5` (select baud)
- Linux serial: `/dev/ttyACM0`
- UDP listener: `udpin:0.0.0.0:14550` (verify the SITL/vehicle sender port)
- TCP example: `tcp:127.0.0.1:5760`

Connection is only reported connected after a MAVLink heartbeat is received. **Never connect a real vehicle to test a new command before confirming the endpoint and using a safe test setup.**

## Project architecture
```
React / TypeScript / Leaflet UI
        | HTTP + WebSocket
FastAPI local service
        |
pymavlink transport and protocol manager
        |
ArduPilot / PX4 / MAVLink-compatible FC (compatibility must be tested)
```

## Safety
- Flight commands require operator confirmation in the UI and API.
- Calibration and parameter writes are blocked while armed.
- Mission upload is blocked while armed.
- Takeoff requires the vehicle armed and GPS 3D fix.
- Commands require a fresh heartbeat; stale heartbeat blocks commands.
- This is a development build; protections are not a substitute for autopilot failsafes, pilot procedures or validation.

## Build status
See [architecture and development roadmap](docs/architecture.md). Hardware-specific behavior should be verified against the team's flight-controller/autopilot, firmware and vehicle configuration before implementation of further setup workflows.

## Backend checks
Run tests from the backend folder:
```powershell
cd backend
pytest
```
The tests cover API safety gates and local log recording. They do not validate flight hardware or autopilot-specific command behavior.
