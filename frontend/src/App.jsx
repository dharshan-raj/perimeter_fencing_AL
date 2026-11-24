
import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  ArrowDownToLine,
  CalendarDays,
  Camera,
  Check,
  Clock3,
  Crosshair,
  Flame,
  RefreshCw,
  ShieldAlert,
  Users,
  UserCheck,
  UserMinus,
  LogIn,
  LogOut,
} from 'lucide-react';

import { get, post } from './services/api';
import Sidebar from './components/Sidebar';
import StatCard from './components/StatCard';
import CameraFeed from './components/CameraFeed';
import CameraStatus from './components/CameraStatus';
import AlertPanel from './components/AlertPanel';
import {
  DailyActivity,
  EventBreakdown,
  HourlyActivity,
} from './components/AnalyticsPanels';


const pageTitles = {
  dashboard: [
    'Operations overview',
    'Perimeter security activity across the IT Furnace facility.',
  ],
  monitoring: [
    'Live monitoring',
    'Camera 14 live stream and perimeter activity.',
  ],
  headcount: [
    'Gate 3 Headcount',
    'Monitor personnel entry and exit at Plant Entrance Gate 3.',
  ],
  zones: [
    'Restricted zones',
    'Draw and manage the monitored perimeter on the camera view.',
  ],
  alerts: [
    'Security alerts',
    'Review and export recent camera events.',
  ],
  analytics: [
    'Security analytics',
    'Review event activity and alert distribution.',
  ],
  evidence: [
    'Incident evidence',
    'Captured images associated with security alerts.',
  ],
  settings: [
    'System settings',
    'Connection state and local administrative access.',
  ],
};


const formatClock = () =>
  new Date().toLocaleTimeString('en-IN', { hour12: false });

const formatDate = () =>
  new Date().toLocaleDateString('en-IN', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });


function downloadCsv(alerts) {
  const columns = [
    'event_timestamp',
    'event_type',
    'severity',
    'person_tracking_id',
    'zone_name',
    'crossing_direction',
    'alert_status',
  ];

  const quote = value =>
    `"${String(value ?? '').replaceAll('"', '""')}"`;

  const csv = [
    columns,
    ...alerts.map(alert => columns.map(key => alert[key])),
  ]
    .map(row => row.map(quote).join(','))
    .join('\r\n');

  const url = URL.createObjectURL(
    new Blob([csv], { type: 'text/csv;charset=utf-8' })
  );

  const link = document.createElement('a');
  link.href = url;
  link.download = `it-furnace-alerts-${new Date()
    .toISOString()
    .slice(0, 10)}.csv`;

  link.click();
  URL.revokeObjectURL(url);
}


function evidenceUrl(path, token) {
  if (!path || !token) return null;

  const normalized = String(path).replaceAll('\\', '/');
  const marker = '/evidence/';

  const relative = normalized.includes(marker)
    ? normalized.split(marker).pop()
    : normalized.replace(/^evidence\//, '');

  const encodedPath = relative
    .split('/')
    .map(encodeURIComponent)
    .join('/');

  return `/api/evidence/${encodedPath}?token=${encodeURIComponent(token)}`;
}


function PageHeading({
  eyebrow = 'IT FURNACE SECURITY',
  title,
  description,
  action,
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="section-kicker">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}


// ---------------------------------------------------------
// EVIDENCE GALLERY
// ---------------------------------------------------------

function EvidenceGallery({ alerts, token }) {
  const [records, setRecords] = useState([]);

  const alertIds = alerts
    .slice(0, 40)
    .map(alert => alert.id)
    .filter(Boolean)
    .join(',');

  useEffect(() => {
    let current = true;

    const ids = alertIds ? alertIds.split(',') : [];

    if (!ids.length) {
      setRecords([]);
      return () => {
        current = false;
      };
    }

    Promise.all(
      ids.map(id => get(`/api/alerts/${id}`).catch(() => null))
    ).then(details => {
      if (current) {
        setRecords(details.filter(record => record?.evidence_path));
      }
    });

    return () => {
      current = false;
    };
  }, [alertIds]);

  return (
    <div className="evidence-grid">
      {records.map(record => {
        const src = evidenceUrl(record.evidence_path, token);

        return (
          <article className="evidence-card" key={record.id}>
            {src ? (
              <img
                src={src}
                alt={`${record.event_type} evidence`}
                loading="lazy"
              />
            ) : (
              <div className="evidence-no-image">
                <ShieldAlert size={22} />
                <span>
                  Enter the admin token in Settings to load evidence.
                </span>
              </div>
            )}

            <div className="evidence-caption">
              <strong>{record.event_type}</strong>
              <span>
                ID {record.person_tracking_id || '—'} ·{' '}
                {record.event_timestamp
                  ? new Date(record.event_timestamp).toLocaleString('en-IN')
                  : 'Timestamp unavailable'}
              </span>
            </div>
          </article>
        );
      })}

      {!records.length && (
        <div className="panel empty-state evidence-empty">
          <ShieldAlert size={22} />
          <strong>No evidence available</strong>
          <span>
            Evidence appears here when an alert includes a captured image.
          </span>
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------
// SETTINGS PANEL
// ---------------------------------------------------------

function SettingsPanel({
  token,
  setToken,
  status,
  videoStatus,
  activeSource,
  processing,
  sourceConfigured,
}) {
  return (
    <div className="settings-grid">
      <section className="panel settings-card">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">ADMIN ACCESS</span>
            <h2>Administrative token</h2>
          </div>
          <ShieldAlert size={18} className="settings-icon" />
        </div>

        <p className="settings-copy">
          Used by this browser for authenticated camera controls, zone
          updates, and evidence images. The token is saved in local
          browser storage.
        </p>

        <label className="form-label" htmlFor="admin-token">
          Admin token
        </label>

        <input
          id="admin-token"
          className="settings-token"
          type="password"
          autoComplete="current-password"
          value={token}
          onChange={event => setToken(event.target.value)}
          placeholder="Enter ADMIN_TOKEN from the backend .env file"
        />

        <span className="form-help">
          The backend never sends its token to the browser. Keep it private.
        </span>
      </section>

      <section className="panel settings-card">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">CAMERA CONNECTION</span>
            <h2>Camera 14 · NVR 2</h2>
          </div>
          <Camera size={18} className="settings-icon" />
        </div>

        <dl className="settings-list">
          <div>
            <dt>Camera state</dt>
            <dd className={`text-${status.toLowerCase()}`}>{status}</dd>
          </div>

          <div>
            <dt>Video stream</dt>
            <dd
              className={
                videoStatus === 'Connected'
                  ? 'text-connected'
                  : 'text-disconnected'
              }
            >
              {videoStatus}
            </dd>
          </div>

          <div>
            <dt>Processing worker</dt>
            <dd>{processing ? 'Running' : 'Stopped'}</dd>
          </div>

          <div>
            <dt>Source type</dt>
            <dd>{activeSource || 'Not selected'}</dd>
          </div>

          <div>
            <dt>Source configured</dt>
            <dd>{sourceConfigured ? 'Yes' : 'No'}</dd>
          </div>
        </dl>

        <p className="form-help">
          Set RTSP_URL or the local camera source in the backend .env file.
          Stream credentials stay on the backend.
        </p>
      </section>
    </div>
  );
}


// ---------------------------------------------------------
// GATE 3 HEADCOUNT PAGE
// ---------------------------------------------------------

function HeadcountPage({ cameraProps }) {
  const [headcount, setHeadcount] = useState({
    total_in: 0,
    total_out: 0,
    current_inside: 0,
  });

  const [events, setEvents] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadHeadcount = async () => {
    try {
      const [liveData, eventData, reportData, attendanceData] = await Promise.all([
        get('/api/headcount/live?gate_name=Gate%203'),
        get('/api/headcount/events?gate_name=Gate%203&limit=25'),
        get('/api/headcount/reports/daily?gate_name=Gate%203'),
        get('/api/headcount/attendance/today'),
      ]);

      setHeadcount({
        total_in: liveData.total_in ?? 0,
        total_out: liveData.total_out ?? 0,
        current_inside: liveData.current_inside ?? 0,
      });

      setEvents(
        Array.isArray(eventData)
          ? eventData
          : eventData.events || []
      );

      setAttendance(
        Array.isArray(attendanceData) ? attendanceData : []
      );

      setReport(reportData);
      setError('');
    } catch (err) {
      setError(
        'Could not load Gate 3 headcount data. Check the backend API.'
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHeadcount();

    const timer = setInterval(loadHeadcount, 5000);

    return () => clearInterval(timer);
  }, []);

  return (
    <div className="headcount-page">
      <div className="panel headcount-header">
        <div>
          <span className="section-kicker">PERSONNEL MONITORING</span>
          <h2>Plant Entrance · Gate 3</h2>
          <p>
            Live entry and exit count using the existing CCTV camera.
          </p>
        </div>

        <button
          className="button-secondary"
          onClick={loadHeadcount}
        >
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="feedback-banner" role="alert">
          {error}
        </div>
      )}

      {cameraProps && (
        <div
          className="headcount-camera-feed"
          style={{
            marginBottom: '1.25rem',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))',
            gap: '1rem',
          }}
        >
          <section className="panel camera-panel">
            <div className="panel-heading">
              <div>
                <span className="section-kicker" style={{ color: '#34d399' }}>
                  CHANNEL 1 · ENTRY CAMERA
                </span>
                <h2>Gate 3 — IN Camera (Channel 1)</h2>
              </div>
              <span className="headcount-direction direction-in">
                <LogIn size={14} /> IN
              </span>
            </div>
            <div className="camera-stage">
              <img
                src="/api/stream_in.mjpg"
                alt="Gate 3 IN Camera (Channel 1)"
                className="camera-video"
                style={{ width: '100%', borderRadius: '0.5rem', display: 'block' }}
              />
            </div>
          </section>

          <div>
            <CameraFeed {...cameraProps} />
          </div>
        </div>
      )}

      <div className="stats-grid">
        <StatCard
          title="Total IN"
          value={headcount.total_in}
          icon={LogIn}
          tone="tone-teal"
          subtitle="People entered through Gate 3"
        />

        <StatCard
          title="Total OUT"
          value={headcount.total_out}
          icon={LogOut}
          tone="tone-blue"
          subtitle="People exited through Gate 3"
        />

        <StatCard
          title="Currently Inside"
          value={headcount.current_inside}
          icon={UserCheck}
          tone="tone-amber"
          subtitle="Calculated from recorded IN and OUT"
        />
      </div>

      <section className="panel headcount-report">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">DAILY SUMMARY</span>
            <h2>Today's Headcount Report</h2>
          </div>
          <CalendarDays size={19} />
        </div>

        {report ? (
          <div className="headcount-report-grid">
            <div>
              <span>Opening count</span>
              <strong>{report.opening_count ?? 0}</strong>
            </div>

            <div>
              <span>Total IN</span>
              <strong>{report.total_in ?? 0}</strong>
            </div>

            <div>
              <span>Total OUT</span>
              <strong>{report.total_out ?? 0}</strong>
            </div>

            <div>
              <span>Closing count</span>
              <strong>{report.closing_count ?? 0}</strong>
            </div>
          </div>
        ) : (
          <p className="form-help">
            {loading ? 'Loading daily report...' : 'No daily report available.'}
          </p>
        )}
      </section>

      <section className="panel headcount-attendance" style={{ marginBottom: '1.25rem' }}>
        <div className="panel-heading">
          <div>
            <span className="section-kicker">EMPLOYEE ATTENDANCE</span>
            <h2>Employee Entry & Exit Timing (Today)</h2>
          </div>
          <Clock3 size={19} />
        </div>

        {attendance.length > 0 ? (
          <div className="table-responsive">
            <table className="headcount-table">
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Status</th>
                  <th>First Entry</th>
                  <th>Last Exit</th>
                  <th>Entries</th>
                  <th>Exits</th>
                </tr>
              </thead>
              <tbody>
                {attendance.map((emp) => (
                  <tr key={emp.employee_name}>
                    <td>
                      <strong style={{ color: '#5eead4', fontSize: '0.95rem' }}>
                        {emp.employee_name}
                      </strong>
                    </td>
                    <td>
                      <span
                        className={
                          emp.status === 'Inside'
                            ? 'headcount-direction direction-in'
                            : 'headcount-direction direction-out'
                        }
                      >
                        {emp.status === 'Inside' ? <LogIn size={13} /> : <LogOut size={13} />}
                        {emp.status}
                      </span>
                    </td>
                    <td>
                      {emp.first_entry
                        ? new Date(emp.first_entry).toLocaleTimeString('en-IN')
                        : '—'}
                    </td>
                    <td>
                      {emp.last_exit
                        ? new Date(emp.last_exit).toLocaleTimeString('en-IN')
                        : '—'}
                    </td>
                    <td>{emp.total_entries}</td>
                    <td>{emp.total_exits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="form-help" style={{ padding: '0.75rem 0' }}>
            No recognized employee crossings recorded today yet. As employees pass Gate 3, their entry and exit times appear here.
          </p>
        )}
      </section>

      <section className="panel headcount-events">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">RECENT ACTIVITY</span>
            <h2>Gate 3 Entry / Exit Events</h2>
          </div>
          <Activity size={19} />
        </div>

        {events.length > 0 ? (
          <div className="table-responsive">
            <table className="headcount-table">
              <thead>
                <tr>
                  <th>Employee / Person</th>
                  <th>Gate</th>
                  <th>Direction</th>
                  <th>Confidence</th>
                  <th>Time</th>
                </tr>
              </thead>

              <tbody>
                {events.map((event, index) => (
                  <tr key={event.id || event.event_key || index}>
                    <td>
                      {event.employee_name ? (
                        <span style={{ fontWeight: 600, color: '#5eead4' }}>
                          {event.employee_name}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted, #94a3b8)' }}>
                          ID {event.tracking_id ?? '—'}
                        </span>
                      )}
                    </td>
                    <td>{event.gate_name || 'Gate 3'}</td>
                    <td>
                      <span
                        className={
                          event.direction === 'IN'
                            ? 'headcount-direction direction-in'
                            : 'headcount-direction direction-out'
                        }
                      >
                        {event.direction === 'IN' ? (
                          <LogIn size={14} />
                        ) : (
                          <LogOut size={14} />
                        )}
                        {event.direction || '—'}
                      </span>
                    </td>
                    <td>
                      {event.confidence != null
                        ? `${(Number(event.confidence) * 100).toFixed(1)}%`
                        : '—'}
                    </td>
                    <td>
                      {event.event_timestamp
                        ? new Date(event.event_timestamp).toLocaleString('en-IN')
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">
            <Users size={22} />
            <strong>No entry or exit events yet</strong>
            <span>
              Confirmed Gate 3 crossings will appear here.
            </span>
          </div>
        )}
      </section>
    </div>
  );
}


// ---------------------------------------------------------
// MAIN APPLICATION
// ---------------------------------------------------------

export default function App() {
  const [page, setPage] = useState('dashboard');

  const [stats, setStats] = useState({});
  const [alerts, setAlerts] = useState([]);

  const [daily, setDaily] = useState({
    daily: [],
    hourly: [],
    event_types: [],
  });

  const [status, setStatus] = useState('Disconnected');
  const [videoStatus, setVideoStatus] = useState('Disconnected');
  const [activeSource, setActiveSource] = useState(null);
  const [sourceConfigured, setSourceConfigured] = useState(false);
  const [processing, setProcessing] = useState(false);

  const [reconnectInfo, setReconnectInfo] = useState({
    attempt: 0,
    wait: 0,
    enabled: true,
  });

  const [zone, setZone] = useState({
    name: 'Restricted Area',
    mode: 'crossing',
    points: [],
  });

  const [zoneEditing, setZoneEditing] = useState(false);
  const [connected, setConnected] = useState(false);
  const [clock, setClock] = useState(formatClock());
  const [filter, setFilter] = useState('All');

  const [token, setToken] = useState(
    () => localStorage.getItem('adminToken') || ''
  );

  const [feedback, setFeedback] = useState('');
  const [refreshing, setRefreshing] = useState(false);


  // -------------------------------------------------------
  // REFRESH EXISTING PERIMETER DATA
  // -------------------------------------------------------

  const refresh = async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);

    try {
      const [
        summary,
        recentAlerts,
        analytics,
        camera,
        currentZone,
      ] = await Promise.all([
        get('/api/analytics/summary'),
        get('/api/alerts?limit=100'),
        get('/api/analytics/daily'),
        get('/api/cameras/14/status'),
        get('/api/zones'),
      ]);

      setStats(summary);
      setAlerts(recentAlerts);
      setDaily(analytics);

      setStatus(camera.stream_status || 'Disconnected');

      setVideoStatus(
        camera.video_status || camera.stream_status || 'Disconnected'
      );

      setActiveSource(camera.active_source || camera.source_type);
      setSourceConfigured(Boolean(camera.source_configured));
      setProcessing(Boolean(camera.processing));

      setReconnectInfo({
        attempt: camera.reconnect_attempt || 0,
        wait: camera.retry_in_seconds || 0,
        enabled: camera.auto_reconnect !== false,
      });

      setZone(currentZone);
    } catch {
      setFeedback(
        'Could not reach the backend API. Check that the backend is running on port 8000.'
      );
    } finally {
      if (showSpinner) setRefreshing(false);
    }
  };


  // -------------------------------------------------------
  // INITIAL LOAD AND WEBSOCKET
  // -------------------------------------------------------

  useEffect(() => {
    refresh();

    const refreshTimer = setInterval(() => {
      setClock(formatClock());
      refresh();
    }, 5000);

    let socket;
    let reconnectTimer;
    let active = true;

    const connect = () => {
      if (!active) return;

      socket = new WebSocket(
        `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/alerts`
      );

      socket.onopen = () => setConnected(true);

      socket.onmessage = event => {
        try {
          const alert = JSON.parse(event.data);

          setAlerts(current =>
            [
              alert,
              ...current.filter(item => item.id !== alert.id),
            ].slice(0, 100)
          );

          refresh();
        } catch {
          // Ignore malformed event messages.
        }
      };

      socket.onclose = () => {
        setConnected(false);

        if (active) {
          reconnectTimer = setTimeout(connect, 2500);
        }
      };

      socket.onerror = () => socket?.close();
    };

    connect();

    return () => {
      active = false;
      clearInterval(refreshTimer);
      clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);


  // -------------------------------------------------------
  // ADMIN TOKEN
  // -------------------------------------------------------

  const handleTokenChange = value => {
    setToken(value);

    if (value) {
      localStorage.setItem('adminToken', value);
    } else {
      localStorage.removeItem('adminToken');
    }
  };


  // -------------------------------------------------------
  // CAMERA MONITORING CONTROL
  // -------------------------------------------------------

  const toggleMonitoring = async () => {
    if (!token.trim()) {
      setFeedback(
        'Enter the admin token in Settings before starting or stopping camera monitoring.'
      );

      setPage('settings');
      return;
    }

    try {
      await post(
        processing
          ? '/api/cameras/14/stop'
          : '/api/cameras/14/start',
        undefined,
        token.trim()
      );

      setFeedback(
        processing
          ? 'Camera monitoring is stopping.'
          : 'Camera monitoring is starting.'
      );

      window.setTimeout(() => refresh(), 700);
    } catch (error) {
      setFeedback(
        error.message.includes('401')
          ? 'The admin token was rejected. Check it in Settings.'
          : 'Camera control failed. Check the backend and camera configuration.'
      );
    }
  };


  // -------------------------------------------------------
  // PAGE DATA
  // -------------------------------------------------------

  const filteredAlerts = useMemo(
    () =>
      alerts.filter(
        alert => filter === 'All' || alert.severity === filter
      ),
    [alerts, filter]
  );

  const openAlertCount = alerts.filter(
    alert => alert.alert_status === 'Open'
  ).length;

  const heading = pageTitles[page] || pageTitles.dashboard;

  const cameraProps = {
    zone,
    onZoneChange: setZone,
    status,
    videoStatus,
    sourceConfigured,
    activeSource,
    processing,
    onToggleMonitoring: toggleMonitoring,
    adminToken: token,
    onAdminTokenChange: handleTokenChange,
    editing: zoneEditing,
    setEditing: setZoneEditing,
    reconnectAttempt: reconnectInfo.attempt,
    retryInSeconds: reconnectInfo.wait,
    autoReconnect: reconnectInfo.enabled,
  };

  const pageAction =
    page === 'alerts' ? (
      <button
        className="button-secondary"
        onClick={() => downloadCsv(filteredAlerts)}
      >
        <ArrowDownToLine size={15} />
        Export CSV
      </button>
    ) : page === 'dashboard' ? (
      <button
        className="button-secondary"
        onClick={() => refresh(true)}
        disabled={refreshing}
      >
        <RefreshCw
          size={15}
          className={refreshing ? 'spin' : ''}
        />
        Refresh
      </button>
    ) : null;


  // -------------------------------------------------------
  // RENDER
  // -------------------------------------------------------

  return (
    <div className="soc-app">
      <Sidebar
        active={page}
        onNavigate={next => {
          setFeedback('');
          setPage(next);
        }}
        alertCount={openAlertCount}
      />

      <main className="main-content">
        <header className="topbar">
          <div className="topbar-system">
            <span className="system-mark">
              <ShieldAlert size={17} />
            </span>

            <div>
              <strong>IT FURNACE SECURITY</strong>
              <small>
                CAMERA 14 · NVR 2 · PERIMETER MONITORING
              </small>
            </div>
          </div>

          <div className="topbar-right">
            <CameraStatus status={status} compact />

            <span className="topbar-date">
              <CalendarDays size={14} />
              {formatDate()} <b>{clock}</b>
            </span>

            <button
              className="button-secondary"
              onClick={() => setPage('headcount')}
            >
              <Users size={15} />
              Gate 3
            </button>

            <button
              className="mobile-refresh"
              onClick={() => refresh(true)}
              aria-label="Refresh dashboard"
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </header>


        <div className="content-wrap">
          <PageHeading
            title={heading[0]}
            description={heading[1]}
            action={pageAction}
          />

          {feedback && (
            <div className="feedback-banner" role="status">
              <span>{feedback}</span>

              <button
                onClick={() => setFeedback('')}
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
          )}


          {/* DASHBOARD */}

          {page === 'dashboard' && (
            <>
              <div className="stats-grid">
                <StatCard
                  title="Unique people"
                  value={stats.total_people_detected}
                  icon={Users}
                  tone="tone-teal"
                  subtitle="This monitoring session"
                />

                <StatCard
                  title="Boundary crossings"
                  value={stats.total_crossings}
                  icon={Crosshair}
                  tone="tone-blue"
                  subtitle="Recorded this session"
                />

                <StatCard
                  title="Intrusion alerts"
                  value={stats.total_intrusion_alerts}
                  icon={ShieldAlert}
                  tone="tone-red"
                  subtitle="Critical events"
                />

                <StatCard
                  title="Active incidents"
                  value={stats.active_incidents}
                  icon={Flame}
                  tone="tone-amber"
                  subtitle="Awaiting acknowledgement"
                />
              </div>

              <div className="dashboard-main-grid">
                <CameraFeed {...cameraProps} />

                <AlertPanel
                  alerts={alerts}
                  limit={7}
                  compact
                  onViewAll={() => setPage('alerts')}
                />
              </div>

              <div className="analytics-grid">
                <DailyActivity data={daily.daily} />
                <EventBreakdown data={daily.event_types} />
              </div>
            </>
          )}


          {/* LIVE MONITORING */}

          {page === 'monitoring' && (
            <>
              <div className="monitoring-strip">
                <span>
                  <i
                    className={
                      videoStatus === 'Connected'
                        ? 'strip-dot good'
                        : status === 'Reconnecting'
                          ? 'strip-dot reconnecting'
                          : 'strip-dot bad'
                    }
                  />

                  {videoStatus === 'Connected'
                    ? 'Live stream active'
                    : status === 'Reconnecting'
                      ? reconnectInfo.wait > 0
                        ? `Reconnecting · retry ${reconnectInfo.attempt || 1} in ${Math.ceil(reconnectInfo.wait)}s`
                        : `Reconnecting · opening attempt ${reconnectInfo.attempt + 1}`
                      : status === 'Stopped'
                        ? 'Camera monitoring stopped'
                        : 'Waiting for camera stream'}
                </span>

                <span>
                  <Clock3 size={14} />
                  Last frame{' '}
                  {stats.camera_status === 'Connected'
                    ? 'updating live'
                    : 'not available'}
                </span>
              </div>

              <CameraFeed {...cameraProps} large />

              <div className="stats-grid stats-grid-compact">
                <StatCard
                  title="Unique people"
                  value={stats.total_people_detected}
                  icon={Users}
                  tone="tone-teal"
                  subtitle="Current session"
                />

                <StatCard
                  title="Boundary crossings"
                  value={stats.total_crossings}
                  icon={Crosshair}
                  tone="tone-blue"
                  subtitle="Current session"
                />

                <StatCard
                  title="Active incidents"
                  value={stats.active_incidents}
                  icon={Flame}
                  tone="tone-amber"
                  subtitle="Open alerts"
                />
              </div>
            </>
          )}


          {/* GATE 3 HEADCOUNT */}

          {page === 'headcount' && <HeadcountPage cameraProps={cameraProps} />}


          {/* RESTRICTED ZONES */}

          {page === 'zones' && (
            <div className="zones-layout">
              <div className="zone-instructions panel">
                <div className="zone-instruction-mark">
                  <Crosshair size={18} />
                </div>

                <div>
                  <strong>{zone.name || 'Restricted Area'}</strong>

                  <p>
                    {zone.points?.length || 0} saved vertices ·{' '}
                    {zone.mode || 'crossing'} mode
                  </p>

                  <span>
                    Open the camera feed editor to draw a new polygon.
                    Click at least three points, choose a detection mode,
                    and save.
                  </span>
                </div>
              </div>

              <CameraFeed {...cameraProps} />
            </div>
          )}


          {/* ALERTS */}

          {page === 'alerts' && (
            <section className="panel alerts-page-panel">
              <div className="alert-filterbar">
                <div>
                  <span className="section-kicker">EVENT HISTORY</span>

                  <strong>
                    {filteredAlerts.length}{' '}
                    {filter === 'All'
                      ? 'events'
                      : `${filter.toLowerCase()} events`}
                  </strong>
                </div>

                <label className="filter-select-label">
                  Severity

                  <select
                    value={filter}
                    onChange={event => setFilter(event.target.value)}
                  >
                    <option>All</option>
                    <option>CRITICAL</option>
                    <option>WARNING</option>
                  </select>
                </label>
              </div>

              <AlertPanel alerts={filteredAlerts} />
            </section>
          )}


          {/* ANALYTICS */}

          {page === 'analytics' && (
            <div className="analytics-page-grid">
              <DailyActivity data={daily.daily} />
              <EventBreakdown data={daily.event_types} />
              <HourlyActivity data={daily.hourly} />
            </div>
          )}


          {/* EVIDENCE */}

          {page === 'evidence' && (
            <>
              <div className="section-note">
                <Check size={15} />
                Images are loaded from existing alert details and the
                authenticated evidence endpoint.
              </div>

              <EvidenceGallery alerts={alerts} token={token} />
            </>
          )}


          {/* SETTINGS */}

          {page === 'settings' && (
            <SettingsPanel
              token={token}
              setToken={handleTokenChange}
              status={status}
              videoStatus={videoStatus}
              activeSource={activeSource}
              processing={processing}
              sourceConfigured={sourceConfigured}
            />
          )}


          <footer className="app-footer">
            <span>
              IT FURNACE <i /> PERIMETER SECURITY OPERATIONS
            </span>

            <span className={connected ? 'footer-connected' : ''}>
              <i />{' '}
              {connected
                ? 'REALTIME ALERT LINK CONNECTED'
                : 'REALTIME ALERT LINK RECONNECTING'}
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}
