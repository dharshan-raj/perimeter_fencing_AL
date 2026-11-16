import { useRef, useState } from 'react';
import { Camera, Circle, Maximize2, Play, Radio, WifiOff } from 'lucide-react';
import ZoneEditor from '../ZoneEditor';
import CameraStatus from './CameraStatus';

export default function CameraFeed({ zone, onZoneChange, status, videoStatus, sourceConfigured, activeSource, processing, onToggleMonitoring, adminToken, onAdminTokenChange, editing, setEditing, reconnectAttempt = 0, retryInSeconds = 0, autoReconnect = true, large = false }) {
  const [retry, setRetry] = useState(0);
  const [fps, setFps] = useState(0);
  const frameTimes = useRef([]);
  const retryTimer = useRef(null);
  const connected = videoStatus === 'Connected';
  const displayedAttempt = Math.max(1, reconnectAttempt + (retryInSeconds <= 0 && reconnectAttempt > 0 ? 1 : 0));
  const retryMessage = retryInSeconds > 0 ? `RTSP interrupted · attempt ${displayedAttempt} · retry in ${Math.ceil(retryInSeconds)}s` : `RTSP interrupted · attempting connection ${displayedAttempt}`;
  const recordFrame = () => {
    const now = performance.now();
    frameTimes.current = [...frameTimes.current.filter(time => now - time < 4000), now];
    const samples = frameTimes.current;
    if (samples.length > 1) setFps(Math.round((samples.length - 1) * 1000 / (samples.at(-1) - samples[0])));
  };
  const retryStream = () => {
    window.clearTimeout(retryTimer.current);
    retryTimer.current = window.setTimeout(() => setRetry(value => value + 1), 2500);
  };
  const sourceLabel = activeSource === 'rtsp' ? 'RTSP Camera Stream' : activeSource === 'sample' ? 'Sample video' : activeSource === 'webcam' ? 'Local webcam' : 'Configured source';

  return <section className={`panel camera-panel ${large ? 'camera-panel-large' : ''}`}>
    <div className="camera-panel-heading"><div><span className="section-kicker">LIVE CAMERA FEED</span><h2><span className="camera-title-icon"><Camera size={17} /></span> Camera 14 <span className="heading-muted">/ IT Furnace</span></h2></div>
      <div className="camera-heading-status"><CameraStatus status={status} compact />{connected && activeSource === 'sample' && <span className="sample-source-badge">SAMPLE VIDEO</span>}</div>
    </div>
    <div className="camera-frame feed">
      {sourceConfigured && <img key={retry} className="camera-image" src={`/api/stream.mjpg?retry=${retry}`} onLoad={recordFrame} onError={retryStream} alt="Live CCTV camera stream" />}
      <ZoneEditor zone={zone} onZoneChange={onZoneChange} editing={editing} setEditing={setEditing} videoStatus={videoStatus} adminToken={adminToken} onAdminTokenChange={onAdminTokenChange} />
      <div className="frame-topline"><span><i /> CAM 14 · {sourceLabel}</span><span>{fps ? `${fps} FPS PREVIEW` : 'PREVIEW FPS —'}</span></div>
      {!connected && <div className="camera-offline-overlay"><div className="offline-symbol"><WifiOff size={20} /></div><strong>{status === 'Reconnecting' ? 'Attempting to reconnect' : status === 'Stopped' ? 'Monitoring stopped' : sourceConfigured ? 'Camera stream unavailable' : 'Camera source not configured'}</strong><span>{status === 'Reconnecting' && autoReconnect ? retryMessage : sourceConfigured ? 'Check the RTSP connection and camera network.' : 'Set the camera source in the backend .env file.'}</span></div>}
      {!sourceConfigured && <div className="camera-placeholder"><Radio size={24} /><span>CAMERA 14</span></div>}
      <button className="frame-expand" title="Feed fills the panel" aria-label="Feed fills the panel"><Maximize2 size={14} /></button>
    </div>
    <div id="zone-controls" className="zone-control-slot" />
    <div className="camera-meta-row"><span><Circle size={8} className={connected ? 'meta-green' : 'meta-red'} />{connected ? 'Stream connected' : 'Stream disconnected'}</span><span><Radio size={14} />{sourceLabel}</span><span>Preview {fps ? `${fps} FPS` : '— FPS'}</span>
      <button className={`monitor-control ${processing ? 'stop-control' : ''}`} onClick={onToggleMonitoring} disabled={!processing && !sourceConfigured}>{processing ? 'Stop monitoring' : <><Play size={13} /> Start monitoring</>}</button>
    </div>
  </section>;
}
