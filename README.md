# ROXX GCS — Ground Control Station

A Team ROXX ground-control dashboard prototype. The current release is **simulation-only**: it visualizes generated telemetry and does not issue flight commands.

## Stack
- Frontend: React + TypeScript + Vite
- Backend: FastAPI WebSocket telemetry simulator
- Planned: MAVLink bridge, map/mission planning, video, autonomy integrations

## Run locally

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Backend telemetry simulator
```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend defaults to simulated local telemetry. Backend websocket is available at `ws://localhost:8000/ws/telemetry`.

## Safety
This project is not flight-tested or flight-ready. Real flight-controller connections and command controls are intentionally not enabled. Test future MAVLink work with SITL first and implement independent failsafes.

## Roadmap
- [x] UI dashboard and telemetry demo
- [x] Backend WebSocket simulator
- [ ] Map and mission route editing
- [ ] MAVLink/SITL integration
- [ ] Flight logs and export
- [ ] Camera/video and autonomy integration
