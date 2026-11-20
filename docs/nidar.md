# NIDAR AirMouse integration

The `/nidar` console uses a local metric grid, not GPS or internet map tiles. It shows live onboard occupancy, pose, camera, mission state and up to six survivor tags. It has **Start mission** and **Safety abort** requests only. This is a GCS integration, not a flight stack or a verified emergency stop.

## Onboard pipeline

- **OAK-D Lite → Basalt VIO:** supply calibrated, synchronized stereo and IMU data in the format expected by your Basalt build. Use its estimated pose as odometry. Calibrate camera, IMU, lidar and body extrinsics and verify timestamp alignment on your hardware.
- **2D lidar + odometry → 2D SLAM:** publish an occupancy grid in `map`; transform the estimated body pose into that same frame using your SLAM transform. Use the current map transform for survivor positions too, including after loop closure. The GCS renders the grid; it does not build it from raw scans.
- **FUEL → exploration:** assuming “FULE” means FUEL, the upstream planner expects a 3D occupancy representation. A planar lidar grid by itself is not sufficient input for unmodified FUEL. Integrate a separate compatible 3D map and validate it, or use an explicitly 2D frontier planner if the challenge permits. Neither planner nor sensor drivers are bundled here.
- **Survivor detection:** onboard detection and metric depth/pose association should publish stable IDs and map-frame positions. Define the official grid origin, axis directions, and cell size with the organizers; don't infer cell size from room dimensions.
- **Mission supervisor:** the onboard state machine owns preflight checks, autonomy, return to the shared entry/exit, the 30-minute flight limit and all failsafes. Do not map the GCS abort request directly to a motor cut. Loss of the GCS link must be handled onboard; the GCS cannot guarantee delivery when the link is down. Validate abort, low battery, link loss, geofence and recall in simulation and guarded bench tests before flight.

## Local operation

1. Run a single backend worker and the frontend locally. Set the same `NIDAR_BRIDGE_TOKEN` on the backend and relay. Bind the backend to loopback if using a local relay; otherwise expose only the required backend NIDAR routes to the onboard computer through a trusted private LAN or a firewall/reverse proxy. The existing developer vehicle API is not suitable for exposure to an untrusted network. An isolated network is required; the bridge header is not encryption or operator authentication.
2. Run `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` from `backend/`; start Vite from `frontend/` with `npm run dev` and open `http://localhost:5173/nidar`. Vite proxies the NIDAR API to the backend. For a production build serve `/nidar` as the SPA and proxy `/api/nidar/` on the same origin. Install dependencies before going offline.
3. On a machine with ROS 2 and the standard message packages installed, run `python3 integrations/nidar_ros2_bridge.py` in your sourced ROS environment. Set `NIDAR_GCS_URL` to the GCS backend's LAN URL if the relay is on the onboard computer. Use local DDS only; no public discovery or internet services are needed.

| Relay topic | Type / contract |
| --- | --- |
| `/nidar/map` | `nav_msgs/OccupancyGrid`, axis-aligned in `map`, max 512 × 512 |
| `/nidar/pose` | `geometry_msgs/PoseStamped`, body pose already transformed into `map` |
| `/nidar/camera/compressed` | `sensor_msgs/CompressedImage`, JPEG ≤ 2 MiB |
| `/nidar/mission` | `std_msgs/String`, JSON snapshot metadata below, published continuously (recommended ≥ 2 Hz) |
| `/nidar/operator_request` | `std_msgs/String`, JSON `{id, mission_id, action}`; process idempotently by ID and acknowledge in `/nidar/mission` |

Example `/nidar/mission` payload (dimensions are illustrative):

```json
{
  "mission_id": "run-001",
  "phase": "ready",
  "elapsed_s": 0,
  "message": "Waiting for start",
  "grid_size_m": 1,
  "grid_origin": {"x": 0, "y": 0},
  "entry_exit": {"x": 0.5, "y": 0.5},
  "survivors": [],
  "acknowledged_command_id": null
}
```

Use a new mission ID per run. Phases: `ready`, `exploring`, `returning`, `complete`, `aborted`, `fault`. Survivor entries are `{id, x, y}`. Grid indices are zero-based relative to `grid_origin`, increase with map X/Y, and may be negative for positions below the origin. The relay adds an increasing `sequence`, the `pose`, and `map`. A direct HTTP publisher can bypass ROS and send the complete payload to `PUT /api/nidar/snapshot` and JPEG bytes to `PUT /api/nidar/camera/{mission_id}`, both with `X-Nidar-Token`. Map cells are row-major, +X fastest, starting at the lower-left origin, with values `-1` unknown, `0` free, `100` occupied. Abort can supersede an unacknowledged start. Acknowledgment means the onboard supervisor consumed the request, not that it has completed the action; publish the resultant phase separately.

## macOS Terminal quick start

Install Python 3.11+ and Node.js 20+ (for example, `brew install python node`).
From the repository root, run:

```sh
export NIDAR_BRIDGE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
./scripts/run-nidar.sh --setup
```

Open `http://127.0.0.1:5173/nidar`. The first run installs dependencies and
needs internet; subsequent launches use `./scripts/run-nidar.sh` and do not
install anything. Ctrl+C stops both services. The launcher binds both services
to loopback. For an onboard relay on another device, use the private LAN setup
above and supply the same bridge token on both sides. The Mac runs the GCS;
Basalt, ROS 2 sensor processing and the mission supervisor can remain on Linux
onboard. Optional MAVSDK is not needed to run the NIDAR console.
