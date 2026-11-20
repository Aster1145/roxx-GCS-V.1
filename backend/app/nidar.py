"""Local bridge for onboard NIDAR mission data. Does not send flight commands."""

import hmac
import os
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, FiniteFloat, model_validator

router = APIRouter(prefix="/api/nidar")
ACTIVE = {"exploring", "returning"}
LINK_TIMEOUT = 3
MAX_JPEG = 2 * 1024 * 1024


class Point(BaseModel):
    x: FiniteFloat
    y: FiniteFloat


class Pose(Point):
    yaw_rad: FiniteFloat


class Survivor(Point):
    id: str = Field(min_length=1, max_length=32)


class OccupancyGrid(BaseModel):
    width: int = Field(ge=1, le=512)
    height: int = Field(ge=1, le=512)
    resolution_m: FiniteFloat = Field(gt=0, le=5)
    origin: Point
    cells: list[Literal[-1, 0, 100]] = Field(max_length=512 * 512)

    @model_validator(mode="after")
    def check_dimensions(self):
        if len(self.cells) != self.width * self.height:
            raise ValueError("cells must contain width × height entries")
        return self


class Snapshot(BaseModel):
    mission_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    sequence: int = Field(ge=0)
    phase: Literal["ready", "exploring", "returning", "complete", "aborted", "fault"]
    elapsed_s: FiniteFloat = Field(ge=0)
    message: str = Field(default="", max_length=240)
    grid_size_m: FiniteFloat = Field(gt=0, le=15)
    grid_origin: Point
    entry_exit: Point
    pose: Pose | None = None
    map: OccupancyGrid | None = None
    survivors: list[Survivor] = Field(default_factory=list, max_length=6)
    acknowledged_command_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def check_survivors(self):
        if len({s.id for s in self.survivors}) != len(self.survivors):
            raise ValueError("Survivor IDs must be unique")
        return self


class Bridge:
    snapshot: Snapshot | None = None
    received_at: float | None = None
    camera: bytes | None = None
    camera_at: float | None = None
    command: dict | None = None
    command_at: float | None = None


bridge = Bridge()


def require_bridge_token(token):
    expected = os.environ.get("NIDAR_BRIDGE_TOKEN")
    if not expected:
        raise HTTPException(503, "Set NIDAR_BRIDGE_TOKEN to enable onboard publishing.")
    if not hmac.compare_digest((token or "").encode(), expected.encode()):
        raise HTTPException(401, "Invalid bridge token.")


def age(timestamp):
    return None if timestamp is None else time.monotonic() - timestamp


def pending_command():
    command = bridge.command
    if command and command["action"] == "start" and age(bridge.command_at) > LINK_TIMEOUT:
        bridge.command = None
    return bridge.command


@router.put("/snapshot")
async def publish(snapshot: Snapshot, x_nidar_token: str | None = Header(default=None)):
    require_bridge_token(x_nidar_token)
    previous = bridge.snapshot
    if previous and snapshot.mission_id == previous.mission_id:
        if snapshot.sequence <= previous.sequence:
            raise HTTPException(409, "Snapshot sequence must increase.")
    else:
        bridge.camera = bridge.camera_at = bridge.command = None
    bridge.snapshot = snapshot
    bridge.received_at = time.monotonic()
    pending = pending_command()
    if snapshot.phase in {"complete", "aborted", "fault"} or (
        pending and snapshot.acknowledged_command_id == pending["id"]
    ):
        bridge.command = None
    return {"pending_command": bridge.command}


@router.get("/status")
async def status():
    link_age = age(bridge.received_at)
    return {"snapshot": bridge.snapshot, "link_age_s": link_age,
            "link_live": link_age is not None and link_age <= LINK_TIMEOUT,
            "camera_age_s": age(bridge.camera_at), "pending_command": pending_command()}


@router.put("/camera/{mission_id}", status_code=204)
async def publish_camera(mission_id: str, request: Request, x_nidar_token: str | None = Header(default=None)):
    require_bridge_token(x_nidar_token)
    if request.headers.get("content-type") != "image/jpeg":
        raise HTTPException(415, "Expected image/jpeg.")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_JPEG:
            raise HTTPException(413, "Camera frame exceeds 2 MiB.")
        data.extend(chunk)
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise HTTPException(422, "Invalid JPEG markers.")
    if not bridge.snapshot or bridge.snapshot.mission_id != mission_id:
        raise HTTPException(409, "Publish the matching mission snapshot first.")
    bridge.camera = bytes(data)
    bridge.camera_at = time.monotonic()
    return Response(status_code=204)


@router.get("/camera")
async def camera():
    if bridge.camera is None:
        raise HTTPException(404, "No camera frame received.")
    return Response(bridge.camera, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/command/{action}", status_code=202)
async def command(action: Literal["start", "abort"], request: Request, mission_id: str):
    # Operator mutations come from this GCS, not a cross-origin web page.
    if request.headers.get("x-nidar-operator") != "console":
        raise HTTPException(403, "Missing console request header.")
    snapshot = bridge.snapshot
    if not snapshot or snapshot.mission_id != mission_id:
        raise HTTPException(409, "No matching onboard mission.")
    pending = pending_command()
    if action == "abort" and pending and pending["action"] == "abort":
        return pending
    if action == "start":
        if snapshot.phase != "ready" or pending or age(bridge.received_at) > LINK_TIMEOUT:
            raise HTTPException(409, "A live, ready mission with no pending request is required.")
    elif snapshot.phase not in ACTIVE and not (pending and pending["action"] == "start"):
        raise HTTPException(409, "No active or starting mission to abort.")
    bridge.command_at = time.monotonic()
    bridge.command = {"id": str(uuid4()), "mission_id": mission_id, "action": action}
    return bridge.command
