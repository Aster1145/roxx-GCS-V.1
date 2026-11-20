"""Optional, read-only ArduPilot SITL telemetry through MAVSDK-Python."""

import asyncio
from contextlib import aclosing
from math import isfinite


def load_sdk():
    from mavsdk.asyncio import ComponentType, Configuration, Mavsdk
    from mavsdk.asyncio.plugins.telemetry import TelemetryAsync

    return lambda: (
        Mavsdk(Configuration.create_with_component_type(ComponentType.GROUND_STATION)),
        TelemetryAsync,
    )


def finite_fields(message, *fields):
    return {field: value if isfinite(value) else None for field in fields
            if (value := getattr(message, field)) is not None}


class MavsdkTelemetry:
    def __init__(self, loader=load_sdk):
        self._loader = loader
        self._task = None
        self._reset()

    def _reset(self):
        self._state = "idle"
        self._endpoint = None
        self._system_id = None
        self._error = None
        self._data = {}

    def status(self):
        connected = self._state == "connected"
        return {"state": self._state, "connected": connected, "endpoint": self._endpoint,
                "system_id": self._system_id, "error": self._error,
                "telemetry": dict(self._data) if connected else {}}

    def start(self, port):
        if self._state == "stopping" or (self._task and not self._task.done()):
            raise RuntimeError("Disconnect the existing MAVSDK session first.")
        factory = self._loader()
        self._reset()
        self._endpoint = f"udpin://127.0.0.1:{port}"
        self._state = "connecting"
        self._task = asyncio.create_task(self._run(factory, self._endpoint))
        return self.status()

    async def stop(self):
        task = self._task
        if task:
            if self._state != "stopping":
                self._state = "stopping"
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._task is not task:
                return self.status()
            self._task = None
        self._reset()
        return self.status()

    async def _run(self, factory, endpoint):
        sdk = None
        try:
            sdk, telemetry_factory = factory()
            # Let the SDK finish binding before destroying its native instance.
            opening = asyncio.create_task(sdk.add_any_connection(endpoint))
            try:
                await asyncio.shield(opening)
            except asyncio.CancelledError:
                await asyncio.gather(opening, return_exceptions=True)
                raise
            system = await sdk.first_autopilot(timeout_s=10)
            if system is None:
                raise TimeoutError("No SITL autopilot heartbeat received within 10 seconds.")
            self._system_id = await system.get_system_id()
            telemetry = telemetry_factory(system)
            streams = (
                ("position", telemetry.subscribe_position, lambda m: finite_fields(
                    m, "latitude_deg", "longitude_deg", "absolute_altitude_m", "relative_altitude_m")),
                ("attitude", telemetry.subscribe_attitude_euler, lambda m: finite_fields(
                    m, "roll_deg", "pitch_deg", "yaw_deg")),
                ("battery", telemetry.subscribe_battery, lambda m: finite_fields(
                    m, "voltage_v", "remaining_percent")),
                ("armed", telemetry.subscribe_armed, bool),
                ("flight_mode", telemetry.subscribe_flight_mode, lambda mode: mode.name),
            )
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._watch_connection(system))
                for name, subscribe, convert in streams:
                    tasks.create_task(self._collect(name, subscribe, convert))
        except Exception as exc:
            self._state = "error"
            self._error = str(exc)
        finally:
            if sdk is not None:
                sdk.destroy()

    async def _watch_connection(self, system):
        while True:
            self._state = "connected" if await system.is_connected() else "disconnected"
            if self._state == "disconnected":
                self._data.clear()
            await asyncio.sleep(0.25)

    async def _collect(self, name, subscribe, convert):
        async with aclosing(subscribe()) as updates:
            async for value in updates:
                if self._state == "connected":
                    self._data[name] = convert(value)
