# ROXX GCS Architecture (draft)

## Current prototype
React dashboard displays synthetic telemetry. Optional FastAPI WebSocket server emits a synthetic stream. Flight controls are disabled.

## Planned architecture
```
React Dashboard / Mission Planner / Map / HUD
                  |
             REST + WebSocket
                  |
         GCS backend / telemetry broker
            |                 |
       MAVLink adapter    Companion interface
            |                 |
     Flight controller   Raspberry Pi / autonomy / sensors
```

## Integration phases
1. Test telemetry contract with simulation.
2. Add MAVLink only to SITL (software-in-the-loop).
3. Add heartbeat, stale telemetry, connection status.
4. Add mission upload/download and validation in SITL.
5. Hardware-in-loop before controlled field testing.

## Safety prerequisites
- Vehicle identity confirmation
- Heartbeat watchdog and stale-data warnings
- Arming checks and explicit confirmation
- Geofence and mission validation
- Independent failsafe review
- Current prototype has no command path.
