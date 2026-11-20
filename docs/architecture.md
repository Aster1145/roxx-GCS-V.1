# ROXX GCS Architecture & Roadmap

## Architecture
```
React/TypeScript interface (mission, flight deck, setup, params, logs)
   | HTTP + WebSocket
FastAPI service (local machine)
   | pymavlink transport
Flight controller / MAVLink vehicle
```

The backend uses a single receive thread per MAVLink connection. It parses vehicle messages into a status cache and routes mission-protocol messages through a queue so mission transfer requests are not competing with the telemetry receiver. The local API is intended for development use.

## Implemented modules
- Serial/UDP/TCP endpoint connection with 10-second heartbeat acquisition
- Heartbeat freshness (stale >5 seconds blocks commands and is shown disconnected)
- Vehicle identifiers, mode, armed state and telemetry status
- Requests core message streams on connection (GPS, attitude, global position, HUD, battery/status)
- WebSocket status updates
- Firmware catalog/download and APJ flashing for MatekH743 target using upstream ArduPilot uploader; target mismatch rejected, flash requires confirmation and closed MAVLink transport
- HEX download for initial DFU (external STM32CubeProgrammer required)
- Parameter request/list cache and disarmed parameter writes
- Mode list from vehicle and mode change requests
- Calibration command requests for gyro, accelerometer, compass, barometer, radio and airspeed (autopilot-specific validation still needed)
- Confirmed arm/disarm/land/RTL; takeoff requires armed and GPS 3D fix
- Map route editor, waypoint/takeoff/land coordinate items, route distance, validation, mission upload/download
- JSON mission import/export and parameter backup/restore
- Local JSON Lines telemetry recording start/stop/list/download
- Event feed including STATUSTEXT and command acknowledgments

## Development status / missing functionality
1. **Vehicle identification and setup wizard:** identify ArduPilot/PX4, vehicle frame, firmware version, sensor status and recommend setup path.
2. **Firmware management:** board-specific APJ flashing now works through the upstream uploader. Initial DFU flashing, bootloader recovery and SITL/bench validation remain.
3. **Airframe setup:** frame class/type and limited motor/ESC test implemented; full motor order/direction test workflow, output mapping and ESC setup wizard remain.
4. **Sensor calibrations:** currently command triggers; interactive progress, calibration result parsing, cancellation and specific FC procedures need development and SITL/hardware validation.
5. **Radio setup:** channel monitor implemented; input mapping, failsafe values and calibration visual workflow remain.
6. **Battery setup:** monitor selection, voltage/current calibration and low/critical failsafe profile.
7. **Failsafe/geofence setup:** dedicated ArduPilot/PX4 parameter presets, readback, validation, restore, and warning logic still need implementation; generic parameter editor is available now.
8. **Mission editor:** full command catalog, command parameter panels, mission download fidelity for all item types, home/RTL/rally support, terrain-aware altitude, fence editing and mission simulation.
9. **Flight logs:** telemetry JSONL recorder implemented; binary onboard log retrieval and decoding are not implemented.
10. **Camera/video:** stream discovery, GStreamer/WebRTC, camera metadata and recording integration.
11. **Autonomy:** companion-computer link, obstacle/depth data, offboard/autonomy state, watchdogs and command arbitration.
12. **Validation:** unit tests, API tests, SITL integration, HIL, bench and controlled flight test plans.

## Safety design currently in code
- Commands require a recent heartbeat.
- UI requires confirmation for flight commands.
- API confirmation required for arm/disarm/takeoff/land/RTL.
- Takeoff requires armed and GPS 3D fix.
- LAND/RTL require armed state.
- Mission upload, parameter writes and calibration are blocked while armed.
- Generic raw command endpoint is disabled.
- These are early safety guards, not flight-certified behavior. Autopilot pre-arm/failsafes remain authoritative.

## Test strategy
- Python unit tests for MAVLink message parsing, API validation, mission item serialization and log recorder.
- SITL test against the chosen firmware (ArduPilot or PX4), including lost heartbeat, rejected commands, mission ACK failures and parameter write/readback.
- HIL/bench checklist before propeller installation; controlled test with team safety procedure after review.
