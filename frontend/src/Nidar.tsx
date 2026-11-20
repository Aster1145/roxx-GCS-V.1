import {useEffect, useRef, useState} from 'react';
import './nidar.css';

type Point = {x: number; y: number};
type Grid = {width: number; height: number; resolution_m: number; origin: Point; cells: number[]};
type Snapshot = {
  mission_id: string; phase: string; elapsed_s: number; message: string;
  grid_size_m: number; grid_origin: Point; entry_exit: Point;
  pose: (Point & {yaw_rad: number}) | null; map: Grid | null;
  survivors: (Point & {id: string})[];
};
type Status = {snapshot: Snapshot | null; link_live: boolean; camera_age_s: number | null;
  pending_command: {action: 'start' | 'abort'} | null};
const ROOT = '/api/nidar';
const cell = (s: Snapshot, p: Point) => [Math.floor((p.x - s.grid_origin.x) / s.grid_size_m), Math.floor((p.y - s.grid_origin.y) / s.grid_size_m)];
const phaseLabels: Record<string, string> = {ready: 'Ready to launch', exploring: 'Exploring', returning: 'Returning to exit', complete: 'Mission complete', aborted: 'Mission aborted', fault: 'Onboard fault'};
const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

function IndoorMap({snapshot}: {snapshot: Snapshot | null}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = ref.current?.getContext('2d');
    if (!ctx) return;
    const {width, height} = ctx.canvas;
    ctx.fillStyle = '#0c141e'; ctx.fillRect(0, 0, width, height);
    const s = snapshot, map = s?.map;
    if (!s || !map) return;
    const scale = Math.min((width - 32) / (map.width * map.resolution_m), (height - 32) / (map.height * map.resolution_m));
    const w = map.width * map.resolution_m * scale, h = map.height * map.resolution_m * scale;
    const left = (width - w) / 2, bottom = (height + h) / 2;
    const x = (v: number) => left + (v - map.origin.x) * scale;
    const y = (v: number) => bottom - (v - map.origin.y) * scale;
    const raster = document.createElement('canvas');
    raster.width = map.width; raster.height = map.height;
    const rasterCtx = raster.getContext('2d');
    if (!rasterCtx) return;
    const pixels = rasterCtx.createImageData(map.width, map.height);
    map.cells.forEach((value, i) => {
      const row = Math.floor(i / map.width), col = i % map.width;
      const color = value === 0 ? [65, 85, 104] : value === 100 ? [220, 229, 235] : [23, 35, 48];
      pixels.data.set([...color, 255], ((map.height - row - 1) * map.width + col) * 4);
    });
    rasterCtx.putImageData(pixels, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(raster, left, bottom - h, w, h);
    ctx.save(); ctx.beginPath(); ctx.rect(left, bottom - h, w, h); ctx.clip();
    const step = s.grid_size_m * scale;
    if (step >= 6) {
      const align = (offset: number) => ((offset % step) + step) % step;
      ctx.strokeStyle = '#8396ac80'; ctx.setLineDash([3, 4]); ctx.beginPath();
      for (let dx = align((s.grid_origin.x - map.origin.x) * scale); dx < w; dx += step) {
        ctx.moveTo(left + dx, bottom); ctx.lineTo(left + dx, bottom - h);
      }
      for (let dy = align((s.grid_origin.y - map.origin.y) * scale); dy < h; dy += step) {
        ctx.moveTo(left, bottom - dy); ctx.lineTo(left + w, bottom - dy);
      }
      ctx.stroke(); ctx.setLineDash([]);
    }
    const marker = (p: Point, color: string, label: string) => {
      ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x(p.x), y(p.y), 6, 0, 2 * Math.PI); ctx.fill();
      ctx.font = 'bold 13px system-ui'; ctx.strokeStyle = '#0c141e'; ctx.lineWidth = 3;
      ctx.strokeText(label, x(p.x) + 9, y(p.y) - 7); ctx.fillText(label, x(p.x) + 9, y(p.y) - 7);
    };
    marker(s.entry_exit, '#55dfb3', 'Entry / exit');
    s.survivors.forEach(p => {
      const [col, row] = cell(s, p);
      if (step >= 6) {
        ctx.fillStyle = '#ffbb5340';
        ctx.fillRect(x(s.grid_origin.x + col * s.grid_size_m), y(s.grid_origin.y + (row + 1) * s.grid_size_m), step, step);
      }
      marker(p, '#ffbd66', p.id);
    });
    if (s.pose) {
      ctx.translate(x(s.pose.x), y(s.pose.y)); ctx.rotate(-s.pose.yaw_rad);
      ctx.fillStyle = '#67abff'; ctx.beginPath(); ctx.moveTo(12, 0); ctx.lineTo(-8, -7);
      ctx.lineTo(-5, 0); ctx.lineTo(-8, 7); ctx.closePath(); ctx.fill();
    }
    ctx.restore();
  }, [snapshot]);
  return <div className="nidar-visual"><canvas ref={ref} width={840} height={560} aria-label="Live occupancy grid" />
    {!snapshot?.map && <span className="nidar-placeholder">Waiting for onboard occupancy grid</span>}</div>;
}

export default function Nidar() {
  const [status, setStatus] = useState<Status | null>(null);
  const [offline, setOffline] = useState(false);
  const [frame, setFrame] = useState<string>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const s = status?.snapshot ?? null;
  const live = !offline && status?.link_live;
  const cameraLive = live && status?.camera_age_s != null && status.camera_age_s <= 3;
  useEffect(() => {
    const control = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const r = await fetch(`${ROOT}/status`, {signal: control.signal, cache: 'no-store'});
        if (!r.ok) throw Error();
        setStatus(await r.json()); setOffline(false);
      } catch { if (!control.signal.aborted) setOffline(true); }
      finally { if (!control.signal.aborted) timer = setTimeout(poll, 300); }
    }
    void poll();
    return () => { control.abort(); clearTimeout(timer); };
  }, []);
  useEffect(() => {
    if (!cameraLive) { setFrame(undefined); return; }
    const control = new AbortController();
    let timer: ReturnType<typeof setTimeout>, url: string | undefined;
    async function next() {
      try {
        const r = await fetch(`${ROOT}/camera`, {signal: control.signal, cache: 'no-store'});
        if (!r.ok) throw Error();
        const blob = await r.blob();
        if (control.signal.aborted) return;
        if (url) URL.revokeObjectURL(url);
        url = URL.createObjectURL(blob); setFrame(url);
      } catch { if (!control.signal.aborted) setFrame(undefined); }
      finally { if (!control.signal.aborted) timer = setTimeout(next, 100); }
    }
    void next();
    return () => { control.abort(); clearTimeout(timer); if (url) URL.revokeObjectURL(url); };
  }, [cameraLive, s?.mission_id]);
  async function send(action: 'start' | 'abort') {
    if (!s) return;
    setBusy(true); setError('');
    try {
      const r = await fetch(`${ROOT}/command/${action}?mission_id=${encodeURIComponent(s.mission_id)}`, {
        method: 'POST', headers: {'X-Nidar-Operator': 'console'}, signal: AbortSignal.timeout(4000),
      });
      const result = await r.json();
      if (!r.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Command rejected');
      setStatus(previous => previous && {...previous, pending_command: result});
    } catch (e) { setError(`${action === 'abort' ? 'Abort request' : 'Start request'} not confirmed: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  }
  const active = s?.phase === 'exploring' || s?.phase === 'returning' || status?.pending_command?.action === 'start';
  return <main className="nidar">
    <header><div><div className="nidar-kicker">ROXX GCS / OFFLINE MISSION CONSOLE</div><h1>NIDAR AirMouse</h1><p>GPS-denied indoor search &amp; rescue</p></div>
      <span className={live ? 'nidar-link live' : 'nidar-link'}>{offline ? 'GCS BACKEND OFFLINE' : live ? 'ONBOARD LINK LIVE' : s ? 'ONBOARD LINK STALE' : 'AWAITING ONBOARD LINK'}</span></header>
    <div className="nidar-stats"><section><small>MISSION PHASE</small><strong>{s ? phaseLabels[s.phase] ?? s.phase : 'Standby'}</strong></section><section><small>FLIGHT TIME</small><strong>{clock(s?.elapsed_s ?? 0)} <span className="nidar-time-limit">/ 30:00</span></strong><progress aria-label="Flight time used" max={1800} value={Math.min(s?.elapsed_s ?? 0, 1800)} /></section><section><small>SURVIVORS TAGGED</small><strong>{s?.survivors.length ?? 0} / 6</strong></section><section><small>DRONE GRID (X, Y)</small><strong>{s?.pose ? cell(s, s.pose).join(', ') : '—'}</strong></section></div>
    <div className="nidar-columns"><section><div className="nidar-panel-heading"><h2>Indoor map</h2><span>{s?.map ? `${s.map.resolution_m.toFixed(2)} m / pixel` : 'No map yet'}</span></div><IndoorMap snapshot={s} /><div className="nidar-legend" aria-label="Map legend"><span><i className="occupied"/>Occupied</span><span><i className="free"/>Free</span><span><i className="unknown"/>Unknown</span><span><i className="drone"/>Drone</span><span><i className="survivor"/>Survivor</span><span><i className="entry"/>Entry / exit</span></div>{s && !live && <p role="alert">Map shows last received data.</p>}</section>
    <div className="nidar-side"><section><div className="nidar-panel-heading"><h2>OAK-D Lite camera</h2><span className={frame && cameraLive ? 'camera-live' : undefined}>{frame && cameraLive ? '● Live' : 'No signal'}</span></div><div className="nidar-visual nidar-camera">{frame && cameraLive ? <img src={frame} alt="Live onboard camera" /> : <span className="nidar-placeholder">{s ? 'No fresh camera frame' : 'Waiting for camera stream'}</span>}</div></section>
    <section><h2>Survivor grid tags</h2>{s?.survivors.length ? <ul>{s.survivors.map(p => <li key={p.id}><strong>{p.id}</strong><span>Grid ({cell(s, p).join(', ')})</span></li>)}</ul> : <p>No detections received.</p>}</section></div></div>
    <section className="nidar-controls"><div><h2>Mission supervision</h2><p>{s?.message || 'Autonomy and failsafes run onboard.'}</p>{status?.pending_command && <p role="status">{status.pending_command.action.toUpperCase()} requested · awaiting onboard acknowledgment</p>}{error && <p role="alert">{error}</p>}</div><div className="nidar-buttons">
      <button disabled={!live || s?.phase !== 'ready' || busy || !!status?.pending_command} onClick={() => void send('start')}>Start mission</button>
      <button className="abort" disabled={!active || status?.pending_command?.action === 'abort'} onClick={() => void send('abort')}>Safety abort</button>
    </div></section>
  </main>;
}
