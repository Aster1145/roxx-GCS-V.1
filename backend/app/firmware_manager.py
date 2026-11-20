"""Firmware catalog/download and ArduPilot APJ flash workflow for the Team ROXX FC."""
import hashlib
import json
import re
import threading
import time
import urllib.request
from pathlib import Path
from .vendor import ardupilot_uploader as ap_uploader

BASE="https://firmware.ardupilot.org/Copter"
TARGETS={"standard":"MatekH743","bdshot":"MatekH743-bdshot"}
CHANNELS={"stable","beta","latest"}
class FirmwareManager:
    def __init__(self,cache_dir):
        self.cache=Path(cache_dir);self.cache.mkdir(parents=True,exist_ok=True)
        self.lock=threading.Lock()
        self.flash_state={"active":False,"stage":"idle","progress":0,"message":"Ready","error":None,"result":None}
    def catalog(self,channel="stable",variant="standard"):
        if channel not in CHANNELS or variant not in TARGETS:raise ValueError("Unsupported firmware channel or target.")
        base=f"{BASE}/{channel}/{TARGETS[variant]}/"
        version=self._read_text(base+"firmware-version.txt")
        git=self._read_text(base+"git-version.txt")
        return {"vehicle":"Copter","board":"Matek H743 Mini V3","target":TARGETS[variant],"channel":channel,
            "firmware_version":version.strip(),"git_version":git.strip(),
            "artifacts":[{"kind":"apj","filename":"arducopter.apj","url":base+"arducopter.apj","use":"Flash with ArduPilot bootloader"},
                         {"kind":"hex","filename":"arducopter_with_bl.hex","url":base+"arducopter_with_bl.hex","use":"Initial DFU bootloader + firmware (external STM32 tool required)"},
                         {"kind":"features","filename":"features.txt","url":base+"features.txt","use":"Build feature list"}]}
    def _read_text(self,url):
        with urllib.request.urlopen(url,timeout=20) as response:return response.read().decode("utf-8",errors="replace")
    def download(self,channel,variant,artifact):
        catalog=self.catalog(channel,variant)
        if artifact not in ("apj","hex","features"):raise ValueError("Unsupported artifact type.")
        item=next(x for x in catalog["artifacts"] if x["kind"]==artifact)
        data=self._download_bytes(item["url"])
        if artifact=="apj":
            obj=json.loads(data.decode("utf-8"))
            if not isinstance(obj.get("board_id"),int) or not obj.get("image"):raise ValueError("Firmware APJ metadata is invalid.")
            image=ap_uploader.firmware.__new__(ap_uploader.firmware)
            image.desc=obj
            # Fully validate the compressed firmware payload and expected image size.
            import base64,zlib
            decoded=zlib.decompress(base64.b64decode(obj["image"]))
            if obj.get("image_size") and len(decoded)!=int(obj["image_size"]):raise ValueError("Firmware payload size mismatch.")
        elif artifact=="hex":
            if not data.startswith(b":") or b":00000001FF" not in data.upper():raise ValueError("HEX file validation failed.")
        target_filename=f"{channel}-{variant}-{item['filename']}"
        path=self.cache/target_filename
        path.write_bytes(data)
        meta={"filename":target_filename,"path":str(path),"channel":channel,"variant":variant,"artifact":artifact,
            "bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"firmware_version":catalog["firmware_version"],
            "board_id":obj.get("board_id") if artifact=="apj" else None,"target":catalog["target"]}
        return meta
    def _download_bytes(self,url):
        req=urllib.request.Request(url,headers={"User-Agent":"ROXX-GCS/0.1"})
        with urllib.request.urlopen(req,timeout=60) as response:return response.read()
    def list_cached(self):
        files=[]
        for path in self.cache.glob("*"):
            if not path.is_file():continue
            try:
                parts=path.name.split("-",2)
                channel=parts[0];variant=parts[1]
                artifact="apj" if path.suffix==".apj" else "hex" if path.suffix==".hex" else "other"
                files.append({"filename":path.name,"channel":channel,"variant":variant,"artifact":artifact,"bytes":path.stat().st_size})
            except Exception:continue
        return files
    def start_flash(self,port,filename,confirm):
        if not confirm:raise ValueError("Explicit flash confirmation required.")
        if self.flash_state["active"]:raise RuntimeError("Firmware flash already in progress.")
        if not re.match(r"^(COM[1-9][0-9]*|/dev/(ttyACM[0-9]+|ttyUSB[0-9]+|serial/by-id/[A-Za-z0-9_.:-]+))$",port):raise ValueError("Serial port format not allowed.")
        path=self.cache/filename
        if path.parent!=self.cache or not path.is_file() or path.suffix.lower()!=".apj":raise ValueError("Select a downloaded APJ file from the firmware cache.")
        self.flash_state={"active":True,"stage":"queued","progress":0,"message":"Flash queued","error":None,"result":None}
        worker=threading.Thread(target=self._flash_worker,args=(port,path),daemon=True)
        worker.start()
        return dict(self.flash_state)
    def _flash_worker(self,port,path):
        up=None
        try:
            self._set(stage="identify",progress=5,message="Opening serial bootloader and identifying board")
            fw=ap_uploader.firmware(str(path))
            up=ap_uploader.uploader(port,115200,115200,identify_only=False)
            up.identify()
            board_type=int(up.board_type)
            fw_board=int(fw.property("board_id"))
            self._set(stage="identified",progress=15,message=f"Bootloader detected board ID {board_type}; APJ board ID {fw_board}")
            # The upstream uploader enforces board compatibility and refuses mismatched images.
            self._set(stage="erase",progress=20,message="Erase stage started")
            up.upload(fw,force=False)
            self._set(active=False,stage="complete",progress=100,message="Firmware upload, verification and reboot completed",result={"port":port,"board_id":board_type,"firmware_board_id":fw_board,"filename":path.name})
        except Exception as exc:
            self._set(active=False,stage="failed",progress=0,message="Firmware flash failed",error=str(exc))
        finally:
            if up is not None:
                try:up.close()
                except Exception:pass
    def _set(self,**values):
        with self.lock:self.flash_state.update(values)
    def status(self):
        with self.lock:return dict(self.flash_state)
