import { Activity, Camera, Images, MapPinned, Settings2, ShieldCheck, ShieldAlert, Users } from 'lucide-react';

const items = [
  { id: 'dashboard', label: 'Dashboard', icon: Activity },
  { id: 'monitoring', label: 'Live monitoring', icon: Camera },
  { id: 'movement', label: 'Movement Security', icon: ShieldAlert },
  { id: 'headcount', label: 'Gate 3 Headcount', icon: Users },
  { id: 'zones', label: 'Restricted zones', icon: MapPinned },
  { id: 'evidence', label: 'Evidence', icon: Images },
  { id: 'settings', label: 'Settings', icon: Settings2 },
];

export default function Sidebar({ active, onNavigate }) {
  return <aside className="sidebar">
    <button className="brand" onClick={() => onNavigate('dashboard')} aria-label="IT Furnace Security dashboard">
      <span className="brand-mark"><ShieldCheck size={21} /></span>
      <span className="brand-copy"><strong>IT FURNACE</strong><small>SECURITY SYSTEM</small></span>
    </button>
    <div className="sidebar-section-label">OPERATIONS</div>
    <nav className="nav-list" aria-label="Main navigation">
      {items.map(({ id, label, icon: Icon }) => <button key={id} aria-label={label} title={label} className={`nav-item ${active === id ? 'active' : ''}`} onClick={() => onNavigate(id)}>
        <Icon size={17} /><span>{label}</span>
      </button>)}
    </nav>
    <div className="sidebar-spacer" />
    <div className="sidebar-camera"><span className="camera-mini-icon"><Camera size={15} /></span><span><strong>Camera 14</strong><small>RTSP Stream · IT Furnace</small></span></div>
    <div className="sidebar-footer"><span className="sidebar-live-dot" /> LOCAL SOC CONSOLE <span>v1.0</span></div>
  </aside>;
}
