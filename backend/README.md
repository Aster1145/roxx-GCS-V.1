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
