import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, MousePointer2, Power, RotateCcw, Save, Trash2, X } from 'lucide-react';
import { post } from './services/api';

function paint(canvas, points, cursor, drawing) {
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, rect.width, rect.height);
  if (!points.length) return;
  const xy = points.map(([x, y]) => [x * rect.width, y * rect.height]);
  ctx.lineWidth = 2;
  ctx.strokeStyle = '#f2b94b';
  ctx.fillStyle = 'rgba(242, 185, 75, 0.16)';
  ctx.setLineDash(drawing ? [7, 5] : [6, 4]);
  ctx.beginPath();
  xy.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  if (!drawing && xy.length >= 3) ctx.closePath();
  if (drawing && cursor && xy.length) ctx.lineTo(cursor[0] * rect.width, cursor[1] * rect.height);
  ctx.fill();
  ctx.stroke();
  ctx.setLineDash([]);
  xy.forEach(([x, y], i) => {
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#111a20';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#ffd16c';
    ctx.stroke();
    ctx.fillStyle = '#f7d88f';
    ctx.font = '10px sans-serif';
    ctx.fillText(String(i + 1), x + 7, y - 6);
  });
}

export default function ZoneEditor({ zone, onZoneChange, editing, setEditing, videoStatus, adminToken: sharedToken, onAdminTokenChange }) {
  const canvasRef = useRef(null);
  const [points, setPoints] = useState(zone.points || []);
  const [cursor, setCursor] = useState(null);
  const [mode, setMode] = useState(zone.mode || 'crossing');
  const [localToken, setLocalToken] = useState(() => localStorage.getItem('adminToken') || '');
  const adminToken = sharedToken ?? localToken;
  const setAdminToken = onAdminTokenChange ?? setLocalToken;
  const [saving, setSaving] = useState(false);
  const [startingCamera, setStartingCamera] = useState(false);
  const [message, setMessage] = useState('');
  const [controls, setControls] = useState(null);

  useEffect(() => setControls(document.getElementById('zone-controls')), []);

  useEffect(() => {
    if (editing) return;
    setPoints(zone.points || []);
    setMode(zone.mode || 'crossing');
  }, [zone, editing]);

  const redraw = useCallback(() => paint(canvasRef.current, points, cursor, editing), [points, cursor, editing]);
  useEffect(() => {
    redraw();
    const observer = new ResizeObserver(redraw);
    if (canvasRef.current) observer.observe(canvasRef.current);
    return () => observer.disconnect();
  }, [redraw]);

  const coordinate = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
  };

  const addPoint = (event) => {
    if (!editing) return;
    const point = coordinate(event);
    setPoints(current => [...current, point]);
    setMessage('');
  };

  const save = async () => {
    if (points.length < 3) { setMessage('Add at least 3 points to define the area.'); return; }
    setSaving(true);
    setMessage('');
    try {
      if (!adminToken.trim()) { setMessage('Enter the admin token to save this area.'); setSaving(false); return; }
      localStorage.setItem('adminToken', adminToken.trim());
      const saved = await post('/api/zones', { ...zone, name: zone.name || 'Restricted Area', mode, points }, adminToken.trim());
      onZoneChange(saved);
      setEditing(false);
      setMessage('Restricted area saved.');
    } catch (error) {
      setMessage(error.message.includes('401') ? 'Save failed. Check the admin token.' : 'Could not save the area. Check the connection and admin token.');
    } finally { setSaving(false); }
  };

  const startCamera = async () => {
    if (!adminToken.trim()) { setMessage('Enter the admin token to restart the camera preview.'); return; }
    setStartingCamera(true);
    setMessage('');
    try {
      localStorage.setItem('adminToken', adminToken.trim());
      await post('/api/cameras/14/start', undefined, adminToken.trim());
      setMessage('Camera preview is starting.');
    } catch {
      setMessage('Could not start the camera. Check the admin token and camera connection.');
    } finally { setStartingCamera(false); }
  };

  return <>
    <canvas ref={canvasRef} className={`zone-canvas ${editing ? 'zone-canvas-editing' : ''}`}
      onClick={addPoint}
      onMouseMove={event => editing && setCursor(coordinate(event))}
      onMouseLeave={() => setCursor(null)} aria-label="Restricted area polygon overlay" />
    {controls && createPortal(<div className="zone-tools">
      {!editing ? <button className="zone-action" onClick={() => { setMessage(''); setPoints([]); setMode(zone.mode || 'crossing'); setEditing(true); }}><MousePointer2 size={14} /> Draw new restricted area</button> : <>
        <div className="zone-tool-row">
          <button className="zone-action" onClick={() => setPoints(current => current.slice(0, -1))} disabled={!points.length}><RotateCcw size={13} /> Undo</button>
          <button className="zone-action" onClick={() => setPoints([])} disabled={!points.length}><Trash2 size={13} /> Clear</button>
          <button className="zone-action" onClick={() => { setEditing(false); setPoints(zone.points || []); setMessage(''); }}><X size={13} /> Cancel</button>
        </div>
        <div className="zone-tool-row zone-save-row">
          <select aria-label="Restricted area detection mode" value={mode} onChange={event => setMode(event.target.value)}>
            <option value="crossing">Boundary crossing</option><option value="intrusion">Intrusion</option><option value="approach">Approach warning</option>
          </select>
          <button className="zone-action zone-save" onClick={save} disabled={saving || points.length < 3}><Save size={13} /> {saving ? 'Saving…' : 'Save area'}</button>
        </div>
        <input className="zone-token" type="password" autoComplete="current-password" value={adminToken} onChange={event => setAdminToken(event.target.value)} placeholder="Admin token" aria-label="Admin token" />
        {videoStatus !== 'Connected' && <button className="zone-action zone-camera-start" onClick={startCamera} disabled={startingCamera}><Power size={13} />{startingCamera ? 'Starting camera…' : 'Start camera preview'}</button>}
        <div className="zone-hint">Click the feed to add points · {points.length} point{points.length === 1 ? '' : 's'} · 3 minimum</div>
      </>}
      {message && <div className="zone-message" role="status">{message}</div>}
    </div>, controls)}
    {editing && <div className="zone-edit-indicator"><span /> AREA EDITING</div>}
    {!editing && points.length >= 3 && <div className="zone-label"><Check size={11} /> {zone.name || 'Restricted area'}</div>}
  </>;
}
