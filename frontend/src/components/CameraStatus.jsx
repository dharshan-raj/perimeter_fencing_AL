import { CircleDot } from 'lucide-react';

const labels = {
  connected: 'Connected',
  reconnecting: 'Reconnecting',
  disconnected: 'Disconnected',
  stopped: 'Stopped',
};

export default function CameraStatus({ status = 'disconnected', compact = false }) {
  const key = String(status).toLowerCase();
  const normalized = Object.hasOwn(labels, key) ? key : 'disconnected';
  return <span className={`camera-status status-${normalized} ${compact ? 'camera-status-compact' : ''}`}>
    <CircleDot size={compact ? 12 : 14} className="camera-status-dot" />{labels[normalized]}
  </span>;
}
