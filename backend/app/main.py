import asyncio, math, random, time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
app=FastAPI(title="ROXX GCS Telemetry Simulator",version="0.1.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
@app.get("/")
async def root(): return {"service":"ROXX GCS telemetry simulator","status":"running","safety":"simulation only"}
@app.get("/health")
async def health(): return {"ok":True,"mode":"simulation"}
@app.websocket("/ws/telemetry")
async def telemetry_socket(ws:WebSocket):
    await ws.accept(); started=time.time()
    try:
        while True:
            t=time.time()-started
            payload={"altitude":round(38+4*math.sin(t/8)+random.uniform(-.3,.3),2),"speed":round(8+1.2*math.sin(t/5)+random.uniform(-.15,.15),2),"heading":round((120+t*1.4)%360,1),"battery":round(max(1,94-t/240),1),"latitude":round(12.9718+math.sin(t/35)*.0008,6),"longitude":round(77.5947+math.cos(t/35)*.0008,6),"roll":round(6*math.sin(t/3)+random.uniform(-.5,.5),1),"pitch":round(4*math.cos(t/4)+random.uniform(-.5,.5),1),"sats":random.choice([11,12,13,14]),"mode":"SIMULATED","signal":random.randint(90,98)}
            await ws.send_json(payload); await asyncio.sleep(1)
    except WebSocketDisconnect: pass
    except Exception:
        try: await ws.close()
        except Exception: pass