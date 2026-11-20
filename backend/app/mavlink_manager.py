"""MAVLink connection and vehicle state manager. Real links only; no synthetic telemetry."""
import asyncio, time, threading
from typing import Any
from pymavlink import mavutil

class MavlinkManager:
    def __init__(self):
        self.master=None; self.reader=None; self.lock=threading.RLock(); self.connected=False
        self.last_heartbeat=0.0; self.vehicle_type=None; self.autopilot=None; self.system_id=None; self.component_id=None
        self.mode="UNKNOWN"; self.armed=False; self.telemetry={}; self.params={}; self.param_count=0
        self.events=[]; self.last_error=None; self.endpoint=None
    def _event(self,level,message):
        self.events.insert(0,{"time":time.time(),"level":level,"message":message}); self.events=self.events[:200]
    def connect(self,endpoint,baud=115200):
        with self.lock:
            if self.master: self.disconnect()
            try:
                if endpoint.startswith(("udp:","udpout:","tcp:")): m=mavutil.mavlink_connection(endpoint,baud=baud,autoreconnect=True)
                else: m=mavutil.mavlink_connection(endpoint,baud=baud,autoreconnect=True)
                self.master=m; self.endpoint={"uri":endpoint,"baud":baud}; self.last_error=None
                self._event("info",f"Opening MAVLink connection: {endpoint}")
            except Exception as e: self.last_error=str(e); self._event("error",str(e)); raise
        hb=m.wait_heartbeat(timeout=8)
        if hb is None:
            with self.lock: self.last_error="Heartbeat timeout"; self._event("error","No vehicle heartbeat received (8 s timeout)")
            self.disconnect(); raise TimeoutError("No MAVLink heartbeat received. Check cable, port, baud and vehicle power.")
        with self.lock:
            self.connected=True; self.last_heartbeat=time.time(); self.system_id=m.target_system; self.component_id=m.target_component
            self.vehicle_type=hb.type; self.autopilot=hb.autopilot; self.mode=mavutil.mode_string_v10(hb); self.armed=bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self._event("success",f"Heartbeat from system {self.system_id}, component {self.component_id}; mode {self.mode}")
            self.reader=threading.Thread(target=self._reader_loop,daemon=True); self.reader.start()
        return self.status()
    def disconnect(self):
        with self.lock:
            m=self.master; self.master=None; self.connected=False; self._event("info","MAVLink disconnected")
        if m:
            try: m.close()
            except Exception: pass
    def _reader_loop(self):
        while self.master is not None:
            try:
                m=self.master; msg=m.recv_match(blocking=True,timeout=1)
                if msg is None: continue
                typ=msg.get_type(); d=msg.to_dict(); now=time.time()
                with self.lock:
                    self.last_heartbeat=now if typ=="HEARTBEAT" else self.last_heartbeat
                    if typ=="HEARTBEAT":
                        self.mode=mavutil.mode_string_v10(msg); self.armed=bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED); self.vehicle_type=msg.type; self.autopilot=msg.autopilot
                    elif typ=="SYS_STATUS":
                        self.telemetry.update({"battery_voltage":(msg.voltage_battery/1000 if msg.voltage_battery>=0 else None),"battery_remaining":msg.battery_remaining if msg.battery_remaining>=0 else None,"sensor_health":msg.onboard_control_sensors_health,"sensor_present":msg.onboard_control_sensors_present})
                    elif typ=="GPS_RAW_INT":
                        self.telemetry.update({"latitude":msg.lat/1e7,"longitude":msg.lon/1e7,"gps_altitude":msg.alt/1000,"gps_fix":msg.fix_type,"satellites":msg.satellites_visible,"gps_hdop":msg.eph/100 if msg.eph>=0 else None})
                    elif typ=="GLOBAL_POSITION_INT":
                        self.telemetry.update({"latitude":msg.lat/1e7,"longitude":msg.lon/1e7,"altitude_m":msg.relative_alt/1000,"absolute_altitude_m":msg.alt/1000,"ground_speed_ms":((msg.vx**2+msg.vy**2)**.5)/100,"heading_deg":msg.hdg/100 if msg.hdg!=65535 else None})
                    elif typ=="ATTITUDE":
                        self.telemetry.update({"roll_rad":msg.roll,"pitch_rad":msg.pitch,"yaw_rad":msg.yaw,"roll_deg":msg.roll*57.2958,"pitch_deg":msg.pitch*57.2958,"yaw_deg":msg.yaw*57.2958})
                    elif typ=="VFR_HUD": self.telemetry.update({"airspeed_ms":msg.airspeed,"ground_speed_ms":msg.groundspeed,"heading_deg":msg.heading,"altitude_m":msg.alt,"climb_ms":msg.climb})
                    elif typ=="BATTERY_STATUS": self.telemetry.update({"battery_remaining":msg.battery_remaining,"battery_current_a":msg.current_battery/100 if msg.current_battery>=0 else None})
                    elif typ=="STATUSTEXT": self._event("status",msg.text.strip())
                    elif typ=="PARAM_VALUE":
                        name=msg.param_id.decode(errors="ignore").rstrip("\\x00") if isinstance(msg.param_id,bytes) else str(msg.param_id).rstrip("\\x00")
                        self.params[name]={"value":msg.param_value,"type":msg.param_type,"index":msg.param_index,"count":msg.param_count}; self.param_count=msg.param_count
                    elif typ=="MISSION_CURRENT": self.telemetry.update({"mission_current":msg.seq,"mission_total":msg.total if hasattr(msg,"total") else None})
                    elif typ=="COMMAND_ACK": self._event("ack",f"Command {msg.command} result {msg.result}")
                    self.telemetry["updated_at"]=now
            except Exception as e:
                with self.lock: self.last_error=str(e); self._event("error",f"MAVLink reader: {e}")
                time.sleep(.3)
    def status(self):
        with self.lock:
            return {"connected":self.connected and self.master is not None,"endpoint":self.endpoint,"system_id":self.system_id,"component_id":self.component_id,"vehicle_type":self.vehicle_type,"autopilot":self.autopilot,"mode":self.mode,"armed":self.armed,"heartbeat_age_s":round(time.time()-self.last_heartbeat,1) if self.last_heartbeat else None,"telemetry":dict(self.telemetry),"parameter_count":self.param_count,"last_error":self.last_error}
    def require(self):
        if not self.master or not self.connected: raise RuntimeError("Vehicle is not connected.")
        if self.last_heartbeat and time.time()-self.last_heartbeat>5: raise RuntimeError("Heartbeat is stale (>5 seconds). Command blocked.")
        return self.master
    def request_message(self,msg_id,interval_us):
        m=self.require(); m.mav.command_long_send(m.target_system,m.target_component,mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,0,msg_id,interval_us,0,0,0,0,0)
    def request_parameters(self):
        m=self.require(); m.mav.param_request_list_send(m.target_system,m.target_component); self._event("info","Parameter list requested")
    def read_parameter(self,name):
        m=self.require(); m.mav.param_request_read_send(m.target_system,m.target_component,name.encode(),-1)
    def set_parameter(self,name,value,param_type=None):
        m=self.require(); old=self.params.get(name)
        if param_type is None and old is None: raise ValueError("Parameter type unknown; request parameter list first.")
        ptype=param_type if param_type is not None else old["type"]
        m.mav.param_set_send(m.target_system,m.target_component,name.encode(),float(value),ptype)
        self._event("info",f"Parameter write requested: {name}={value}")
    def command_long(self,command,params=None,confirmation=0):
        m=self.require(); vals=list(params or [])+[0]*7; vals=vals[:7]
        m.mav.command_long_send(m.target_system,m.target_component,int(command),confirmation,*[float(v) for v in vals])
    def set_mode(self,mode):
        m=self.require(); modes=m.mode_mapping()
        if not modes or mode not in modes: raise ValueError(f"Mode {mode} not available. Available modes: {list((modes or {}).keys())}")
        m.set_mode(modes[mode]); self._event("info",f"Mode change requested: {mode}")
    def send_mission(self,items):
        m=self.require(); mav=mavutil.mavlink
        m.mav.mission_clear_all_send(m.target_system,m.target_component)
        time.sleep(.15); m.mav.mission_count_send(m.target_system,m.target_component,len(items),mav.MAV_MISSION_TYPE_MISSION)
        # Mission protocol handshake is handled synchronously in a worker; validate structure beforehand.
        sent=set(); deadline=time.time()+15
        while time.time()<deadline and len(sent)<len(items):
            req=m.recv_match(type=["MISSION_REQUEST_INT","MISSION_REQUEST"],blocking=True,timeout=1)
            if req is None: continue
            seq=int(req.seq); item=items[seq]
            m.mav.mission_item_int_send(m.target_system,m.target_component,seq,int(item.get("frame",mav.MAV_FRAME_GLOBAL_RELATIVE_ALT)),int(item["command"]),int(item.get("current",0)),int(item.get("autocontinue",1)),float(item.get("param1",0)),float(item.get("param2",0)),float(item.get("param3",0)),float(item.get("param4",0)),int(float(item["latitude"])*1e7),int(float(item["longitude"])*1e7),float(item.get("altitude",50)),mav.MAV_MISSION_TYPE_MISSION)
            sent.add(seq)
        ack=m.recv_match(type="MISSION_ACK",blocking=True,timeout=5)
        if ack is None: raise TimeoutError("Mission upload timed out waiting for ACK.")
        if ack.type!=mav.MAV_MISSION_ACCEPTED: raise RuntimeError(f"Vehicle rejected mission upload: ACK {ack.type}")
        self._event("success",f"Uploaded {len(items)} mission items")
        return {"uploaded":len(items),"ack":ack.type}
    def get_modes(self):
        m=self.require(); return list((m.mode_mapping() or {}).keys())
    def close(self): self.disconnect()
