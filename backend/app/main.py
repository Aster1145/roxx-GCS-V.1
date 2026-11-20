"""ROXX GCS backend: local REST API and MAVLink WebSocket telemetry."""
import asyncio, json, threading, time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .mavlink_manager import MavlinkManager
manager=MavlinkManager()
app=FastAPI(title="ROXX Ground Control Station",version="0.2.0",description="Local vehicle control API. Only connect to a vehicle you own/operate.")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
class ConnectRequest(BaseModel):
    endpoint:str=Field(min_length=2,description="Serial device path or MAVLink endpoint, e.g. COM5, /dev/ttyACM0, udp:127.0.0.1:14550")
    baud:int=115200
class ParamWrite(BaseModel):
    name:str; value:float
class CommandRequest(BaseModel):
    command:int; params:list[float]=[]
class ModeRequest(BaseModel):
    mode:str
class MissionItem(BaseModel):
    latitude:float; longitude:float; altitude:float=50
    command:int=16; frame:int=3; current:int=0; autocontinue:int=1
    param1:float=0;param2:float=0;param3:float=0;param4:float=0
class MissionUpload(BaseModel):
    items:list[MissionItem]
@app.get("/")
def root():return {"service":"ROXX GCS","version":"0.2.0","connection":"real MAVLink, no mock telemetry"}
@app.get("/api/health")
def health():return {"ok":True,"connected":manager.status()["connected"]}
@app.get("/api/vehicle/status")
def vehicle_status():return manager.status()
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
@app.get("/api/vehicle/parameters/{name}")
def read_param(name:str):
    try:manager.read_parameter(name);return {"requested":name}
    except Exception as e:raise HTTPException(400,str(e))
@app.put("/api/vehicle/parameters/{name}")
def write_param(name:str,req:ParamWrite):
    try:manager.set_parameter(name,req.value);return {"requested":name,"value":req.value}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/command")
def command(req:CommandRequest):
    try:manager.command_long(req.command,req.params);return {"command_sent":req.command}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/vehicle/mission/upload")
def mission_upload(req:MissionUpload):
    if not req.items:raise HTTPException(400,"Mission is empty")
    try:
        return manager.send_mission([i.model_dump() for i in req.items])
    except Exception as e:raise HTTPException(400,str(e))
@app.get("/api/events")
def events():return {"events":manager.events}
@app.websocket("/ws/telemetry")
async def telemetry_ws(ws:WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(manager.status());await asyncio.sleep(.25)
    except WebSocketDisconnect:pass
