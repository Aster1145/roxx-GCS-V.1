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
