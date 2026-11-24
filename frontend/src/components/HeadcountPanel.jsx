
import { useEffect, useState, useCallback } from 'react';
import {
    Users,
    LogIn,
    LogOut,
    UserCheck,
    CalendarDays,
    RefreshCw,
    Activity,
} from 'lucide-react';

import { get } from '../services/api';


export default function HeadcountPanel() {
    const [headcount, setHeadcount] = useState({
        total_in: 0,
        total_out: 0,
        current_inside: 0,
    });

    const [events, setEvents] = useState([]);
    const [report, setReport] = useState(null);

    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState('');


    // --------------------------------------------------
    // LOAD HEADCOUNT DATA
    // --------------------------------------------------

    const loadHeadcount = useCallback(async (manual = false) => {
        if (manual) setRefreshing(true);

        try {
            const [liveData, eventData, reportData] = await Promise.all([
                get('/api/headcount/live?gate_name=Gate%203'),
                get('/api/headcount/events?gate_name=Gate%203&limit=20'),
                get('/api/headcount/reports/daily?gate_name=Gate%203'),
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

            setReport(reportData);
            setError('');

        } catch (err) {
            setError(
                'Unable to load headcount data. Check the backend connection.'
            );
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, []);


    // --------------------------------------------------
    // AUTOMATIC REFRESH
    // --------------------------------------------------

    useEffect(() => {
        loadHeadcount();

        const interval = setInterval(() => {
            loadHeadcount();
        }, 5000);

        return () => clearInterval(interval);
    }, [loadHeadcount]);


    // --------------------------------------------------
    // FORMAT DATE
    // --------------------------------------------------

    const formatTimestamp = timestamp => {
        if (!timestamp) return '—';

        const date = new Date(timestamp);

        if (Number.isNaN(date.getTime())) return '—';

        return date.toLocaleString('en-IN');
    };


    // --------------------------------------------------
    // RENDER
    // --------------------------------------------------

    return (
        <div className="headcount-page">

            {/* HEADER */}

            <div className="panel headcount-header">
                <div>
                    <span className="section-kicker">
                        PERSONNEL MONITORING
                    </span>

                    <h2>Plant Entrance · Gate 3</h2>

                    <p>
                        Monitor personnel entering and leaving the plant.
                    </p>
                </div>

                <button
                    className="button-secondary"
                    onClick={() => loadHeadcount(true)}
                    disabled={refreshing}
                >
                    <RefreshCw
                        size={15}
                        className={refreshing ? 'spin' : ''}
                    />
                    Refresh
                </button>
            </div>


            {/* ERROR MESSAGE */}

            {error && (
                <div className="feedback-banner" role="alert">
                    {error}
                </div>
            )}


            {/* LIVE HEADCOUNT CARDS */}

            <div className="stats-grid">

                <div className="panel headcount-stat-card">
                    <div className="headcount-stat-icon direction-in">
                        <LogIn size={22} />
                    </div>

                    <span>Total IN</span>

                    <strong>
                        {loading ? '...' : headcount.total_in}
                    </strong>

                    <small>People entered</small>
                </div>


                <div className="panel headcount-stat-card">
                    <div className="headcount-stat-icon direction-out">
                        <LogOut size={22} />
                    </div>

                    <span>Total OUT</span>

                    <strong>
                        {loading ? '...' : headcount.total_out}
                    </strong>

                    <small>People exited</small>
                </div>


                <div className="panel headcount-stat-card">
                    <div className="headcount-stat-icon">
                        <UserCheck size={22} />
                    </div>

                    <span>Currently Inside</span>

                    <strong>
                        {loading ? '...' : headcount.current_inside}
                    </strong>

                    <small>Calculated occupancy</small>
                </div>

            </div>


            {/* DAILY REPORT */}

            <section className="panel headcount-report">

                <div className="panel-heading">
                    <div>
                        <span className="section-kicker">
                            DAILY SUMMARY
                        </span>

                        <h2>Today's Headcount Report</h2>
                    </div>

                    <CalendarDays size={20} />
                </div>


                {report ? (
                    <div className="headcount-report-grid">

                        <div>
                            <span>Opening Count</span>
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
                            <span>Closing Count</span>
                            <strong>{report.closing_count ?? 0}</strong>
                        </div>

                    </div>
                ) : (
                    <p className="form-help">
                        {loading
                            ? 'Loading report...'
                            : 'No report available.'}
                    </p>
                )}

            </section>


            {/* RECENT EVENTS */}

            <section className="panel headcount-events">

                <div className="panel-heading">
                    <div>
                        <span className="section-kicker">
                            ENTRY / EXIT HISTORY
                        </span>

                        <h2>Recent Gate 3 Events</h2>
                    </div>

                    <Activity size={20} />
                </div>


                {events.length > 0 ? (

                    <div className="table-responsive">

                        <table className="headcount-table">

                            <thead>
                                <tr>
                                    <th>Tracking ID</th>
                                    <th>Gate</th>
                                    <th>Direction</th>
                                    <th>Confidence</th>
                                    <th>Timestamp</th>
                                </tr>
                            </thead>

                            <tbody>
                                {events.map((event, index) => (

                                    <tr
                                        key={
                                            event.id ||
                                            event.event_key ||
                                            index
                                        }
                                    >

                                        <td>
                                            {event.tracking_id ?? '—'}
                                        </td>

                                        <td>
                                            {event.gate_name || 'Gate 3'}
                                        </td>

                                        <td>
                                            <span
                                                className={
                                                    event.direction === 'IN'
                                                        ? 'headcount-direction direction-in'
                                                        : 'headcount-direction direction-out'
                                                }
                                            >
                                                {event.direction === 'IN'
                                                    ? <LogIn size={14} />
                                                    : <LogOut size={14} />
                                                }

                                                {event.direction || '—'}
                                            </span>
                                        </td>

                                        <td>
                                            {event.confidence != null
                                                ? `${(
                                                    Number(event.confidence) * 100
                                                ).toFixed(1)}%`
                                                : '—'}
                                        </td>

                                        <td>
                                            {formatTimestamp(
                                                event.event_timestamp
                                            )}
                                        </td>

                                    </tr>

                                ))}
                            </tbody>

                        </table>

                    </div>

                ) : (

                    <div className="empty-state">
                        <Users size={24} />

                        <strong>
                            No entry or exit events yet
                        </strong>

                        <span>
                            Confirmed Gate 3 crossings will appear here.
                        </span>
                    </div>

                )}

            </section>

        </div>
    );
}
