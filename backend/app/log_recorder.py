"""Local JSONL telemetry recorder. Records only actual vehicle/backend status."""
import asyncio
import json
import time
from pathlib import Path
class FlightLogRecorder:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.task=None;self.file=None;self.filename=None;self.recording=False
    async def start(self,get_status):
        if self.recording:raise RuntimeError("Recording already active.")
        self.filename=time.strftime("roxx-flight-%Y%m%d-%H%M%S.jsonl")
        self.file=(self.root/self.filename).open("a",encoding="utf-8")
        self.recording=True
        self.task=asyncio.create_task(self._run(get_status))
        return {"recording":True,"filename":self.filename}
    async def _run(self,get_status):
        try:
            while self.recording:
                self.file.write(json.dumps({"timestamp":time.time(),"status":get_status()},default=str)+"\n")
                self.file.flush()
                await asyncio.sleep(1)
        finally:
            if self.file:
                self.file.close();self.file=None
    async def stop(self):
        if not self.recording:return {"recording":False,"filename":self.filename}
        self.recording=False
        if self.task:
            await self.task;self.task=None
        return {"recording":False,"filename":self.filename}
    def list_logs(self):
        return sorted([{"name":p.name,"size_bytes":p.stat().st_size,"modified":p.stat().st_mtime} for p in self.root.glob("roxx-flight-*.jsonl")],key=lambda x:x["modified"],reverse=True)
