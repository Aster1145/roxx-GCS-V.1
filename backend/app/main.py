"""ROXX GCS backend API - real MAVLink telemetry and control."""
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path
from fastapi.responses import FileResponse
from .log_recorder import FlightLogRecorder
from pymavlink import mavutil
from .mavlink_manager import MavlinkManager
manager=MavlinkManager()
recorder=FlightLogRecorder(Path(__file__).resolve().parent.parent/'logs')
app=FastAPI(title="ROXX Ground Control Station",version="0.4.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
class ConnectRequest(BaseModel):
    endpoint:str=Field(min_length=2); baud:int=115200
class ParamWrite(BaseModel):
    value:float
class ConfirmRequest(BaseModel):
    confirm:bool=False
class TakeoffRequest(BaseModel):
    confirm:bool=False; altitude:float=Field(default=10,ge=1,le=120)
class ModeRequest(BaseModel):
    mode:str
class MissionItem(BaseModel):
    latitude:float;longitude:float;altitude:float=Field(default=30,ge=1,le=500)
    command:int=16;frame:int=3;current:int=0;autocontinue:int=1
    param1:float=0;param2:float=0;param3:float=0;param4:float=0
class MissionUpload(BaseModel):
    items:list[MissionItem]
@app.get("/")
def root():return {"service":"ROXX GCS","version":"0.4.0","telemetry":"real MAVLink"}
@app.get("/api/health")
def health():return {"ok":True,"connected":manager.status()["connected"]}
@app.get("/api/vehicle/status")
def status():return manager.status()
@app.post("/api/vehicle/connect")
def connect(req:ConnectRequest):
    try:return manager.connect(req.endpoint,req.baud)
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/disconnect")
def disconnect():manager.disconnect();return {"disconnected":True}
@app.get("/api/vehicle/modes")
def modes():
    try:return {"modes":manager.get_modes()}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/mode")
def set_mode(req:ModeRequest):
    try:manager.set_mode(req.mode);return {"requested":req.mode}
    except Exception as e:raise HTTPException(400,str(e))
@app.get("/api/vehicle/parameters")
def parameters():return {"count":manager.param_count,"parameters":manager.params}
@app.post("/api/vehicle/parameters/request")
def request_params():
    try:manager.request_parameters();return {"requested":True}
    except Exception as e:raise HTTPException(400,str(e))
@app.put("/api/vehicle/parameters/{name}")
def write_param(name:str,req:ParamWrite):
    try:manager.set_parameter(name,req.value);return {"requested":name,"value":req.value}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/command")
def command(req:ConfirmRequest):
    raise HTTPException(400,"Raw command endpoint intentionally disabled; use specific safety-checked controls.")
@app.post("/api/vehicle/calibration/{kind}")
def calibration(kind:str):
    if manager.armed:raise HTTPException(400,"Calibration blocked while armed.")
    calibration_map={"gyro":[1,0,0,0,0,0,0],"compass":[0,1,0,0,0,0,0],"pressure":[0,0,1,0,0,0,0],"radio":[0,0,0,1,0,0,0],"accelerometer":[0,0,0,0,1,0,0],"airspeed":[0,0,0,0,0,1,0]}
    if kind not in calibration_map:raise HTTPException(404,"Unknown calibration type")
    try:manager.command_long(mavutil.mavlink.MAV_CMD_PREFLIGHT_CALIBRATION,calibration_map[kind]);return {"calibration_requested":kind}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/arm")
def arm(req:ConfirmRequest):
    if not req.confirm:raise HTTPException(400,"Explicit operator confirmation required.")
    if manager.armed:raise HTTPException(400,"Vehicle is already armed.")
    try:manager.command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,[1,0]);return {"requested":"arm"}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/disarm")
def disarm(req:ConfirmRequest):
    if not req.confirm:raise HTTPException(400,"Explicit operator confirmation required.")
    try:manager.command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,[0,0]);return {"requested":"disarm"}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/takeoff")
def takeoff(req:TakeoffRequest):
    if not req.confirm:raise HTTPException(400,"Explicit operator confirmation required.")
    if not manager.armed:raise HTTPException(400,"Takeoff requires vehicle armed.")
    if manager.telemetry.get("gps_fix",0)<3:raise HTTPException(400,"Takeoff blocked: GPS 3D fix required.")
    try:manager.command_long(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,[0,0,0,0,0,0,req.altitude]);return {"requested":"takeoff","altitude":req.altitude}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/land")
def land(req:ConfirmRequest):
    if not req.confirm:raise HTTPException(400,"Explicit operator confirmation required.")
    if not manager.armed:raise HTTPException(400,"LAND command requires armed vehicle.")
    try:manager.command_long(mavutil.mavlink.MAV_CMD_NAV_LAND,[0,0,0,0,0,0,0]);return {"requested":"land"}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/rtl")
def rtl(req:ConfirmRequest):
    if not req.confirm:raise HTTPException(400,"Explicit operator confirmation required.")
    if not manager.armed:raise HTTPException(400,"RTL command requires armed vehicle.")
    try:manager.command_long(mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,[0,0,0,0,0,0,0]);return {"requested":"rtl"}
    except Exception as e:raise HTTPException(400,str(e))
@app.get("/api/vehicle/mission/download")
def download_mission():
    try:return manager.download_mission()
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/mission/upload")
def upload(req:MissionUpload):
    if not req.items:raise HTTPException(400,"Mission plan is empty")
    if len(req.items)>500:raise HTTPException(400,"Mission item limit is 500")
    try:return manager.upload_mission([i.model_dump() for i in req.items])
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/logs/start")
async def start_log():
    try:return await recorder.start(manager.status)
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/logs/stop")
async def stop_log():
    try:return await recorder.stop()
    except Exception as e:raise HTTPException(400,str(e))
@app.get("/api/logs")
def list_logs():return {"recording":recorder.recording,"current":recorder.filename,"files":recorder.list_logs()}
@app.get("/api/logs/{name}/download")
def download_log(name:str):
    if "/" in name or "\\" in name or not name.endswith(".jsonl"):raise HTTPException(400,"Invalid log filename")
    target=recorder.root/name
    if not target.exists():raise HTTPException(404,"Log not found")
    return FileResponse(target,media_type="application/json",filename=name)
@app.get("/api/events")
def events():return {"events":manager.events}
@app.websocket("/ws/telemetry")
async def telemetry(ws:WebSocket):
    await ws.accept()
    try:
        while True:await ws.send_json(manager.status());await asyncio.sleep(.3)
    except WebSocketDisconnect:pass
