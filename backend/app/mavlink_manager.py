"""Real MAVLink connection manager. This module never fabricates telemetry."""
import queue
import threading
import time
from pymavlink import mavutil

class MavlinkManager:
    def __init__(self):
        self.master = None
        self.reader = None
        self.lock = threading.RLock()
        self.connected = False
        self.last_heartbeat = 0
        self.vehicle_type = None
        self.autopilot = None
        self.system_id = None
        self.component_id = None
        self.mode = "UNKNOWN"
        self.armed = False
        self.telemetry = {}
        self.params = {}
        self.param_count = 0
        self.events = []
        self.last_error = None
        self.endpoint = None
        self.mission_queue = queue.Queue()

    def event(self, level, message):
        self.events.insert(0, {"time": time.time(), "level": level, "message": str(message)})
        del self.events[200:]

    def connect(self, endpoint, baud=115200):
        self.disconnect()
        self.telemetry = {}; self.params = {}; self.param_count = 0; self.last_error = None
        self.system_id = None; self.component_id = None; self.vehicle_type = None; self.autopilot = None; self.mode = "UNKNOWN"; self.armed = False; self.last_heartbeat = 0
        try:
            master = mavutil.mavlink_connection(endpoint, baud=baud, autoreconnect=True)
            self.master = master
            self.endpoint = {"uri": endpoint, "baud": baud}
            self.event("info", f"Connecting to {endpoint}; waiting for heartbeat")
            heartbeat = master.wait_heartbeat(timeout=10)
            if heartbeat is None:
                self.last_error = "No heartbeat within 10 seconds"
                self.event("error", self.last_error)
                self.disconnect()
                raise TimeoutError("No MAVLink heartbeat received. Check vehicle power, cable, port and baud.")
            self.connected = True
            self.last_heartbeat = time.time()
            self.system_id = master.target_system
            self.component_id = master.target_component
            self.vehicle_type = heartbeat.type
            self.autopilot = heartbeat.autopilot
            self.mode = mavutil.mode_string_v10(heartbeat)
            self.armed = bool(heartbeat.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self.last_error = None
            self.event("success", f"Vehicle heartbeat received (sys {self.system_id}, comp {self.component_id})")
            self.reader = threading.Thread(target=self.reader_loop, daemon=True)
            self.reader.start()
            self.request_streams()
            return self.status()
        except Exception as exc:
            self.last_error = str(exc)
            raise

    def disconnect(self):
        master = self.master
        self.master = None
        self.connected = False
        if master:
            try:
                master.close()
            except Exception:
                pass

    def request_streams(self):
        """Ask MAVLink-capable autopilots for core telemetry rates."""
        if not self.master or not self.connected: return
        rates = {1:1000000, 24:1000000, 30:250000, 33:500000, 74:1000000, 147:1000000}
        for message_id, interval_us in rates.items():
            try:
                self.master.mav.command_long_send(self.master.target_system,self.master.target_component,
                    mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,0,message_id,interval_us,0,0,0,0,0)
            except Exception as exc:
                self.event("warning", f"Telemetry rate request for message {message_id} failed: {exc}")
        self.event("info", "Requested core MAVLink telemetry streams")
    def request_autopilot_version(self):
        if not self.master or not self.connected: return
        try:
            self.master.mav.command_long_send(self.master.target_system,self.master.target_component,
                mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,0,mavutil.mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION,0,0,0,0,0,0)
            self.event("info", "Requested autopilot firmware/version information")
        except Exception as exc:
            self.event("warning", f"Autopilot version request failed: {exc}")
    def reader_loop(self):
        while self.master is not None:
            try:
                master = self.master
                msg = master.recv_match(blocking=True, timeout=1)
                if msg is None:
                    continue
                typ = msg.get_type()
                with self.lock:
                    if typ == "HEARTBEAT":
                        self.last_heartbeat = time.time()
                        self.mode = mavutil.mode_string_v10(msg)
                        self.armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                        self.vehicle_type, self.autopilot = msg.type, msg.autopilot
                    elif typ == "AUTOPILOT_VERSION":
                        v = int(msg.flight_sw_version)
                        self.telemetry.update({"firmware_version": f"{(v>>24)&255}.{(v>>16)&255}.{(v>>8)&255}", "firmware_vendor_id": msg.vendor_id, "firmware_product_id": msg.product_id, "capabilities": msg.capabilities})
                    elif typ == "SYS_STATUS":
                        self.telemetry.update({
                            "battery_voltage": msg.voltage_battery / 1000 if msg.voltage_battery >= 0 else None,
                            "battery_remaining": msg.battery_remaining if msg.battery_remaining >= 0 else None,
                            "sensor_health": msg.onboard_control_sensors_health,
                            "sensor_present": msg.onboard_control_sensors_present})
                    elif typ == "GPS_RAW_INT":
                        self.telemetry.update({"gps_fix": msg.fix_type, "satellites": msg.satellites_visible if msg.satellites_visible != 255 else None,
                            "gps_hdop": msg.eph / 100 if msg.eph >= 0 else None})
                    elif typ == "GLOBAL_POSITION_INT":
                        self.telemetry.update({"latitude": msg.lat/1e7, "longitude": msg.lon/1e7,
                            "altitude_m": msg.relative_alt/1000, "absolute_altitude_m": msg.alt/1000,
                            "ground_speed_ms": ((msg.vx**2+msg.vy**2)**.5)/100,
                            "heading_deg": msg.hdg/100 if msg.hdg != 65535 else None})
                    elif typ == "ATTITUDE":
                        self.telemetry.update({"roll_deg": msg.roll*57.2958, "pitch_deg": msg.pitch*57.2958,
                            "yaw_deg": msg.yaw*57.2958})
                    elif typ == "VFR_HUD":
                        self.telemetry.update({"airspeed_ms": msg.airspeed, "ground_speed_ms": msg.groundspeed,
                            "heading_deg": msg.heading, "altitude_m": msg.alt, "climb_ms": msg.climb})
                    elif typ == "BATTERY_STATUS":
                        self.telemetry.update({"battery_remaining": msg.battery_remaining,
                            "battery_current_a": msg.current_battery/100 if msg.current_battery >= 0 else None})
                    elif typ == "STATUSTEXT":
                        self.event("status", msg.text.strip())
                    elif typ == "PARAM_VALUE":
                        name = msg.param_id.decode(errors="ignore").rstrip("\x00") if isinstance(msg.param_id, bytes) else str(msg.param_id).rstrip("\x00")
                        self.params[name] = {"value": msg.param_value, "type": msg.param_type,
                            "index": msg.param_index, "count": msg.param_count}
                        self.param_count = msg.param_count
                    elif typ == "MISSION_CURRENT":
                        self.telemetry["mission_current"] = msg.seq
                    elif typ == "COMMAND_ACK":
                        self.event("ack", f"Command {msg.command} result {msg.result}")
                    if typ in ("MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK", "MISSION_ITEM_INT", "MISSION_ITEM", "MISSION_COUNT"):
                        self.mission_queue.put(msg)
                    self.telemetry["updated_at"] = time.time()
            except Exception as exc:
                self.last_error = str(exc)
                self.event("error", f"MAVLink receive error: {exc}")
                time.sleep(.2)

    def status(self):
        with self.lock:
            return {"connected": bool(self.connected and self.master and self.last_heartbeat and time.time()-self.last_heartbeat <= 5), "endpoint": self.endpoint,
                "system_id": self.system_id, "component_id": self.component_id,
                "vehicle_type": self.vehicle_type, "autopilot": self.autopilot,
                "mode": self.mode, "armed": self.armed,
                "heartbeat_age_s": round(time.time()-self.last_heartbeat, 1) if self.last_heartbeat else None,
                "telemetry": dict(self.telemetry), "parameter_count": self.param_count,
                "last_error": self.last_error}

    def require(self):
        if not self.master or not self.connected:
            raise RuntimeError("Vehicle is not connected.")
        if self.last_heartbeat and time.time()-self.last_heartbeat > 5:
            raise RuntimeError("Heartbeat stale (>5 s). Command blocked.")
        return self.master

    def request_parameters(self):
        m = self.require()
        m.mav.param_request_list_send(m.target_system, m.target_component)
        self.event("info", "Parameter list requested from vehicle")

    def read_parameter(self, name):
        m = self.require()
        m.mav.param_request_read_send(m.target_system, m.target_component, name.encode(), -1)

    def set_parameter(self, name, value):
        m = self.require()
        if self.armed:
            raise RuntimeError("Parameter writes blocked while armed. Disarm the vehicle first.")
        current = self.params.get(name)
        if current is None:
            raise ValueError("Parameter not loaded. Request/download the parameter list first.")
        m.mav.param_set_send(m.target_system, m.target_component, name.encode(), float(value), current["type"])
        m.mav.param_request_read_send(m.target_system, m.target_component, name.encode(), -1)
        self.event("info", f"Parameter set requested and read-back requested: {name}={value}")

    def command_long(self, command, params=None):
        m = self.require()
        vals = list(params or []) + [0] * 7
        m.mav.command_long_send(m.target_system, m.target_component, int(command), 0, *[float(v) for v in vals[:7]])

    def set_mode(self, mode):
        m = self.require()
        mapping = m.mode_mapping() or {}
        if mode not in mapping:
            raise ValueError(f"Unsupported mode: {mode}. Vehicle reports: {list(mapping.keys())}")
        m.set_mode(mapping[mode])
        self.event("info", f"Mode change requested: {mode}")

    def get_modes(self):
        return list((self.require().mode_mapping() or {}).keys())

    def download_mission(self):
        m = self.require()
        mav = mavutil.mavlink
        while not self.mission_queue.empty():
            try: self.mission_queue.get_nowait()
            except queue.Empty: break
        m.mav.mission_request_list_send(m.target_system, m.target_component, mav.MAV_MISSION_TYPE_MISSION)
        deadline = time.time() + 10
        count = None
        while time.time() < deadline:
            try: msg = self.mission_queue.get(timeout=.75)
            except queue.Empty: continue
            if msg.get_type() == "MISSION_COUNT":
                count = int(msg.count); break
        if count is None: raise TimeoutError("Vehicle did not return mission count.")
        if count > 500: raise RuntimeError("Vehicle mission exceeds safety limit (500 items).")
        result = []
        for seq in range(count):
            m.mav.mission_request_int_send(m.target_system, m.target_component, seq, mav.MAV_MISSION_TYPE_MISSION)
            deadline = time.time() + 8
            item = None
            while time.time() < deadline:
                try: msg = self.mission_queue.get(timeout=.75)
                except queue.Empty: continue
                if msg.get_type() not in ("MISSION_ITEM_INT", "MISSION_ITEM"): continue
                if int(msg.seq) != seq: continue
                item = msg; break
            if item is None: raise TimeoutError(f"Mission item {seq} download timed out.")
            is_int = item.get_type() == "MISSION_ITEM_INT"
            x = item.x / 1e7 if is_int else item.x
            y = item.y / 1e7 if is_int else item.y
            result.append({"seq":seq,"latitude":x,"longitude":y,"altitude":item.z,
                "command":item.command,"frame":item.frame,"current":item.current,
                "autocontinue":item.autocontinue,"param1":item.param1,"param2":item.param2,
                "param3":item.param3,"param4":item.param4})
        self.event("success", f"Downloaded vehicle mission ({count} items)")
        return {"count":count,"items":result}

    def upload_mission(self, items):
        m = self.require()
        mav = mavutil.mavlink
        if self.armed:
            raise RuntimeError("Mission upload blocked while armed. Disarm before uploading.")
        while not self.mission_queue.empty():
            try: self.mission_queue.get_nowait()
            except queue.Empty: break
        # MISSION_COUNT starts a replacement transfer; avoid a separate clear-all ACK race.
        m.mav.mission_count_send(m.target_system, m.target_component, len(items), mav.MAV_MISSION_TYPE_MISSION)
        received = set()
        deadline = time.time() + 25
        ack = None
        while time.time() < deadline:
            try: msg = self.mission_queue.get(timeout=.75)
            except queue.Empty: continue
            typ = msg.get_type()
            if typ in ("MISSION_REQUEST_INT", "MISSION_REQUEST"):
                seq = int(msg.seq)
                if seq < 0 or seq >= len(items):
                    raise ValueError(f"Vehicle requested invalid mission item index {seq}")
                item = items[seq]
                m.mav.mission_item_int_send(m.target_system, m.target_component, seq,
                    int(item.get("frame", mav.MAV_FRAME_GLOBAL_RELATIVE_ALT)),
                    int(item.get("command", mav.MAV_CMD_NAV_WAYPOINT)), int(item.get("current", 0)),
                    int(item.get("autocontinue", 1)), float(item.get("param1", 0)), float(item.get("param2", 0)),
                    float(item.get("param3", 0)), float(item.get("param4", 0)),
                    int(float(item["latitude"])*1e7), int(float(item["longitude"])*1e7),
                    float(item.get("altitude", 50)), mav.MAV_MISSION_TYPE_MISSION)
                received.add(seq)
            elif typ == "MISSION_ACK":
                ack = msg
                break
        if ack is None:
            raise TimeoutError("Mission transfer timeout; no final vehicle ACK.")
        if ack.type != mav.MAV_MISSION_ACCEPTED:
            raise RuntimeError(f"Vehicle rejected mission transfer (ACK={ack.type}).")
        self.event("success", f"Mission upload acknowledged ({len(items)} items)")
        return {"uploaded": len(items), "ack": ack.type}
