import React, { useState, useEffect } from 'react';
import {
  ShieldAlert,
  Users,
  UserCheck,
  UserX,
  AlertTriangle,
  RefreshCw,
  Clock,
  MapPin,
  Calendar,
  Filter,
  Eye,
  CheckCircle,
} from 'lucide-react';
import { get } from '../services/api';
import StatCard from './StatCard';
import CameraFeed from './CameraFeed';

export default function MovementSecurityPage({ cameraProps, token }) {
  const [summary, setSummary] = useState({
    total_detected: 0,
    authorised_count: 0,
    unknown_count: 0,
    unauthorised_count: 0,
    today_violations: 0,
    restricted_zones_active: 0,
    is_working_hours: true,
  });

  const [zones, setZones] = useState([]);
  const [events, setEvents] = useState([]);
  const [totalEvents, setTotalEvents] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Filters
  const [filterSeverity, setFilterSeverity] = useState('ALL');
  const [filterType, setFilterType] = useState('ALL');
  const [filterStatus, setFilterStatus] = useState('ALL');
  const [filterDate, setFilterDate] = useState('');
  const [selectedSnapshot, setSelectedSnapshot] = useState(null);

  const loadData = async () => {
    try {
      const [sumRes, zonesRes] = await Promise.all([
        get('/api/movement/summary'),
        get('/api/movement/zones'),
      ]);

      setSummary(sumRes);
      if (zonesRes && zonesRes.zones) {
        setZones(zonesRes.zones);
      }
      setError('');
    } catch (err) {
      console.error('Movement summary load error:', err);
      setError('Could not load movement monitoring summary.');
    }
  };

  const loadEvents = async () => {
    try {
      let url = '/api/movement/events?limit=30';
      if (filterSeverity !== 'ALL') url += `&severity=${filterSeverity}`;
      if (filterType !== 'ALL') url += `&event_type=${filterType}`;
      if (filterStatus !== 'ALL') url += `&identity_status=${filterStatus}`;
      if (filterDate) url += `&date=${filterDate}`;

      const res = await get(url);
      setEvents(res.events || []);
      setTotalEvents(res.total || 0);
    } catch (err) {
      console.error('Movement events load error:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    loadEvents();
    const interval = setInterval(() => {
      loadData();
      loadEvents();
    }, 4000);
    return () => clearInterval(interval);
  }, [filterSeverity, filterType, filterStatus, filterDate]);

  const getStatusBadge = (status) => {
    if (status === 'AUTHORISED') {
      return (
        <span className="movement-badge badge-green">
          <UserCheck size={13} /> AUTHORISED
        </span>
      );
    }
    if (status === 'UNAUTHORISED') {
      return (
        <span className="movement-badge badge-red">
          <UserX size={13} /> UNAUTHORISED
        </span>
      );
    }
    return (
      <span className="movement-badge badge-yellow">
        <Users size={13} /> UNKNOWN
      </span>
    );
  };

  const getSeverityBadge = (sev) => {
    const s = (sev || 'HIGH').toUpperCase();
    if (s === 'CRITICAL') {
      return <span className="movement-pill pill-critical">CRITICAL</span>;
    }
    if (s === 'HIGH') {
      return <span className="movement-pill pill-high">HIGH</span>;
    }
    if (s === 'MEDIUM') {
      return <span className="movement-pill pill-medium">MEDIUM</span>;
    }
    return <span className="movement-pill pill-low">LOW</span>;
  };

  return (
    <div className="movement-page">
      {/* Header */}
      <div className="panel movement-header">
        <div>
          <span className="section-kicker" style={{ color: '#ef4444' }}>
            FACTORY SECURITY · AI SURVEILLANCE
          </span>
          <h2>Unauthorised Movement Monitoring</h2>
          <p>
            Real-time human movement tracking, role-based restricted zone authorization, and unauthorized intruder detection.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            className={`status-pill ${summary.is_working_hours ? 'pill-green' : 'pill-amber'}`}
            title="Operational hours status"
          >
            <Clock size={14} />
            <span>{summary.is_working_hours ? 'OPERATIONAL HOURS' : 'AFTER-HOURS MONITORING'}</span>
          </div>

          <button className="button-secondary" onClick={() => { loadData(); loadEvents(); }}>
            <RefreshCw size={15} /> Refresh
          </button>
        </div>
      </div>

      {error && <div className="feedback-banner" role="alert">{error}</div>}

      {/* Camera Live View + Controlled Zones Status */}
      <div className="movement-top-grid">
        <div className="panel" style={{ padding: '1rem' }}>
          <div className="panel-heading" style={{ marginBottom: '0.75rem' }}>
            <div>
              <span className="section-kicker" style={{ color: '#38bdf8' }}>LIVE RTSP STREAM</span>
              <h3>Factory CCTV Surveillance</h3>
            </div>
            <div className="live-pill">
              <span className="strip-dot good" /> ACTIVE
            </div>
          </div>
          <CameraFeed {...cameraProps} large />
        </div>

        {/* Zones & Rules Panel */}
        <div className="panel movement-rules-panel">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">MONITORED ZONES</span>
              <h3>Active Controlled Areas</h3>
            </div>
            <MapPin size={18} style={{ color: '#f59e0b' }} />
          </div>

          <div className="zones-list">
            {zones.map((z) => (
              <div key={z.zone_id} className="zone-card">
                <div className="zone-card-header">
                  <span
                    className="zone-dot"
                    style={{ backgroundColor: z.color || '#ef4444' }}
                  />
                  <strong>{z.zone_name}</strong>
                  <span className="zone-type-tag">{z.zone_type}</span>
                </div>
                <div className="zone-card-body">
                  <div>
                    <span className="zone-meta-label">Severity:</span>
                    <span style={{ fontWeight: 600 }}>{z.severity}</span>
                  </div>
                  <div>
                    <span className="zone-meta-label">Allowed:</span>
                    <span>
                      {z.allowed_employees.length > 0
                        ? z.allowed_employees.slice(0, 3).join(', ') + (z.allowed_employees.length > 3 ? '...' : '')
                        : z.allowed_roles.join(', ') || 'None'}
                    </span>
                  </div>
                  {z.after_hours_restricted && (
                    <div className="zone-afterhours-flag">
                      <Clock size={12} /> After-Hours Strict Lock
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Summary KPI Cards */}
      <div className="stats-grid" style={{ marginTop: '1.25rem' }}>
        <StatCard
          title="Current Detected"
          value={summary.total_detected}
          icon={Users}
          tone="tone-blue"
          subtitle="People in camera view"
        />

        <StatCard
          title="Authorised Persons"
          value={summary.authorised_count}
          icon={UserCheck}
          tone="tone-teal"
          subtitle="Identified registered employees"
        />

        <StatCard
          title="Unknown Persons"
          value={summary.unknown_count}
          icon={Users}
          tone="tone-amber"
          subtitle="Unregistered / Unconfirmed"
        />

        <StatCard
          title="Today's Violations"
          value={summary.today_violations}
          icon={ShieldAlert}
          tone="tone-red"
          subtitle="Unauthorised movement events"
        />
      </div>

      {/* Movement Security Alerts & Event History */}
      <section className="panel movement-events-panel" style={{ marginTop: '1.5rem' }}>
        <div className="panel-heading" style={{ flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <span className="section-kicker">INCIDENT LOGS</span>
            <h2>Unauthorised Movement Alert History</h2>
            <p style={{ fontSize: '0.875rem', color: '#94a3b8' }}>
              Showing {events.length} of {totalEvents} recorded events
            </p>
          </div>

          {/* Filter Bar */}
          <div className="movement-filter-bar">
            <div className="filter-group">
              <label>Severity</label>
              <select value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)}>
                <option value="ALL">All Severities</option>
                <option value="CRITICAL">CRITICAL</option>
                <option value="HIGH">HIGH</option>
                <option value="MEDIUM">MEDIUM</option>
              </select>
            </div>

            <div className="filter-group">
              <label>Event Type</label>
              <select value={filterType} onChange={(e) => setFilterType(e.target.value)}>
                <option value="ALL">All Event Types</option>
                <option value="UNAUTHORISED_MOVEMENT">Unauthorised Movement</option>
                <option value="UNKNOWN_PERSON_DETECTION">Unknown Person</option>
                <option value="AFTER_HOURS_MOVEMENT">After-Hours Movement</option>
                <option value="RESTRICTED_ZONE_ENTRY">Restricted Zone Entry</option>
              </select>
            </div>

            <div className="filter-group">
              <label>Identity</label>
              <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
                <option value="ALL">All Identities</option>
                <option value="UNAUTHORISED">UNAUTHORISED</option>
                <option value="UNKNOWN">UNKNOWN</option>
                <option value="AUTHORISED">AUTHORISED</option>
              </select>
            </div>

            <div className="filter-group">
              <label>Date</label>
              <input
                type="date"
                value={filterDate}
                onChange={(e) => setFilterDate(e.target.value)}
                style={{
                  background: '#1e293b',
                  color: '#f8fafc',
                  border: '1px solid #334155',
                  padding: '0.35rem 0.5rem',
                  borderRadius: '0.375rem',
                  fontSize: '0.85rem',
                }}
              />
            </div>
          </div>
        </div>

        {/* Events Table */}
        <div className="movement-table-wrapper">
          {events.length === 0 ? (
            <div className="empty-events-state">
              <CheckCircle size={32} style={{ color: '#10b981', marginBottom: '0.5rem' }} />
              <p>No unauthorised movements detected matching current filters.</p>
            </div>
          ) : (
            <table className="movement-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Tracking ID</th>
                  <th>Identity</th>
                  <th>Event Type</th>
                  <th>Restricted Zone</th>
                  <th>Severity</th>
                  <th>Description</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {events.map((evt) => (
                  <tr key={evt.id} className={evt.severity === 'CRITICAL' ? 'row-critical' : ''}>
                    <td style={{ whiteSpace: 'nowrap', fontSize: '0.85rem' }}>
                      {evt.event_timestamp ? new Date(evt.event_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-'}
                      <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                        {evt.event_timestamp ? new Date(evt.event_timestamp).toLocaleDateString() : ''}
                      </div>
                    </td>
                    <td>
                      <span className="tid-badge">#{evt.tracking_id}</span>
                    </td>
                    <td>
                      {getStatusBadge(evt.identity_status)}
                      {evt.employee_name && (
                        <div style={{ fontSize: '0.775rem', color: '#cbd5e1', marginTop: '2px', fontWeight: 500 }}>
                          {evt.employee_name}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className="event-type-badge">
                        {evt.event_type.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontWeight: 500, color: '#f1f5f9' }}>{evt.zone_name}</span>
                    </td>
                    <td>{getSeverityBadge(evt.severity)}</td>
                    <td style={{ fontSize: '0.85rem', color: '#cbd5e1', maxWidth: '300px' }}>
                      {evt.description || '-'}
                    </td>
                    <td>
                      {evt.snapshot_path ? (
                        <button
                          className="button-icon-preview"
                          onClick={() => setSelectedSnapshot(evt.snapshot_path)}
                          title="View evidence snapshot"
                        >
                          <Eye size={15} /> Snapshot
                        </button>
                      ) : (
                        <span style={{ color: '#475569', fontSize: '0.8rem' }}>None</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {/* Snapshot Preview Modal */}
      {selectedSnapshot && (
        <div className="snapshot-modal-overlay" onClick={() => setSelectedSnapshot(null)}>
          <div className="snapshot-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="snapshot-modal-header">
              <h3>Incident Snapshot Preview</h3>
              <button className="button-close" onClick={() => setSelectedSnapshot(null)}>✕</button>
            </div>
            <div className="snapshot-modal-body">
              <img
                src={selectedSnapshot}
                alt="Incident Snapshot"
                style={{ width: '100%', maxHeight: '70vh', objectFit: 'contain', borderRadius: '0.375rem' }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
