import { ArrowUpRight, ShieldAlert } from 'lucide-react';

const formatTime = value => value ? new Date(value).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : 'Time unavailable';

function AlertRow({ alert }) {
  const severity = (alert.severity || 'WARNING').toLowerCase();
  return <article className="security-alert-row">
    <div className={`alert-icon ${severity}`}><ShieldAlert size={17} /></div>
    <div className="alert-main"><strong>{(alert.event_type || 'Security event').replaceAll('_', ' ')}</strong><span>Tracking ID {alert.person_tracking_id || '—'} <i /> {formatTime(alert.event_timestamp)}</span></div>
    <span className={`severity-badge ${severity}`}>{alert.severity || 'WARNING'}</span>
  </article>;
}

export default function AlertPanel({ alerts = [], limit, onViewAll, compact = false }) {
  const rows = limit ? alerts.slice(0, limit) : alerts;
  return <section className={`panel alert-panel ${compact ? 'compact-panel' : ''}`}>
    <div className="panel-heading"><div><span className="section-kicker">SECURITY EVENTS</span><h2>Recent security alerts <span className="heading-count">{alerts.length}</span></h2></div>{onViewAll && <button className="text-action" onClick={onViewAll}>View all <ArrowUpRight size={14} /></button>}</div>
    <div className="alert-list">{rows.map((alert, index) => <AlertRow key={alert.id || `${alert.event_timestamp}-${index}`} alert={alert} />)}
      {!rows.length && <div className="empty-state"><ShieldAlert size={20} /><strong>No alerts to display</strong><span>Security events will appear here when detected.</span></div>}
    </div>
  </section>;
}
