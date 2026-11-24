
import { useEffect, useState, useCallback } from 'react';
import {
    CalendarDays,
    RefreshCw,
    Users,
    LogIn,
    LogOut,
    TrendingUp,
    BarChart3,
} from 'lucide-react';

import {
    ResponsiveContainer,
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
} from 'recharts';

import { get } from '../services/api';


export default function HeadcountAnalytics() {
    const today = new Date();

    const [year, setYear] = useState(today.getFullYear());
    const [month, setMonth] = useState(today.getMonth() + 1);

    const [report, setReport] = useState(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState('');


    // --------------------------------------------------
    // LOAD MONTHLY REPORT
    // --------------------------------------------------

    const loadReport = useCallback(async (manual = false) => {
        if (manual) setRefreshing(true);

        try {
            const data = await get(
                `/api/headcount/reports/monthly?year=${year}&month=${month}&gate_name=Gate%203`
            );

            setReport(data);
            setError('');
        } catch (err) {
            setError(
                'Unable to load monthly headcount report. Check the backend API.'
            );
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [year, month]);


    useEffect(() => {
        loadReport();
    }, [loadReport]);


    // --------------------------------------------------
    // CHART DATA
    // --------------------------------------------------

    const chartData = (report?.daily_reports || []).map(day => ({
        date: new Date(`${day.report_date}T00:00:00`).getDate(),
        IN: day.total_in || 0,
        OUT: day.total_out || 0,
    }));


    // --------------------------------------------------
    // MONTH NAME
    // --------------------------------------------------

    const monthName = new Date(year, month - 1).toLocaleString(
        'en-IN',
        { month: 'long' }
    );


    // --------------------------------------------------
    // RENDER
    // --------------------------------------------------

    return (
        <div className="headcount-analytics">

            {/* HEADER */}

            <div className="panel headcount-header">
                <div>
                    <span className="section-kicker">
                        GATE 3 ANALYTICS
                    </span>

                    <h2>Monthly Headcount Report</h2>

                    <p>
                        Analyze personnel movement at Plant Entrance Gate 3.
                    </p>
                </div>

                <button
                    className="button-secondary"
                    onClick={() => loadReport(true)}
                    disabled={refreshing}
                >
                    <RefreshCw
                        size={15}
                        className={refreshing ? 'spin' : ''}
                    />
                    Refresh
                </button>
            </div>


            {/* MONTH AND YEAR FILTER */}

            <section className="panel headcount-filter">
                <div>
                    <CalendarDays size={18} />
                    <strong>Select Report Period</strong>
                </div>

                <div className="headcount-filter-controls">

                    <label>
                        Month

                        <select
                            value={month}
                            onChange={event => setMonth(Number(event.target.value))}
                        >
                            {Array.from({ length: 12 }, (_, index) => (
                                <option key={index + 1} value={index + 1}>
                                    {new Date(2000, index).toLocaleString(
                                        'en-IN',
                                        { month: 'long' }
                                    )}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label>
                        Year

                        <select
                            value={year}
                            onChange={event => setYear(Number(event.target.value))}
                        >
                            {Array.from(
                                { length: 5 },
                                (_, index) => today.getFullYear() - index
                            ).map(value => (
                                <option key={value} value={value}>
                                    {value}
                                </option>
                            ))}
                        </select>
                    </label>

                </div>
            </section>


            {/* ERROR */}

            {error && (
                <div className="feedback-banner" role="alert">
                    {error}
                </div>
            )}


            {/* MONTHLY SUMMARY */}

            <div className="stats-grid">

                <div className="panel headcount-stat-card">
                    <div className="headcount-stat-icon direction-in">
                        <LogIn size={22} />
                    </div>

                    <span>Total IN</span>

                    <strong>
                        {loading ? '...' : report?.total_in ?? 0}
                    </strong>

                    <small>Personnel entered this month</small>
                </div>


                <div className="panel headcount-stat-card">
                    <div className="headcount-stat-icon direction-out">
                        <LogOut size={22} />
                    </div>

                    <span>Total OUT</span>

                    <strong>
                        {loading ? '...' : report?.total_out ?? 0}
                    </strong>

                    <small>Personnel exited this month</small>
                </div>


                <div className="panel headcount-stat-card">
                    <div className="headcount-stat-icon">
                        <Users size={22} />
                    </div>

                    <span>Closing Count</span>

                    <strong>
                        {loading ? '...' : report?.closing_count ?? 0}
                    </strong>

                    <small>Calculated closing occupancy</small>
                </div>


                <div className="panel headcount-stat-card">
                    <div className="headcount-stat-icon">
                        <TrendingUp size={22} />
                    </div>

                    <span>Opening Count</span>

                    <strong>
                        {loading ? '...' : report?.opening_count ?? 0}
                    </strong>

                    <small>Opening occupancy for the month</small>
                </div>

            </div>


            {/* MONTHLY CHART */}

            <section className="panel headcount-chart-panel">

                <div className="panel-heading">
                    <div>
                        <span className="section-kicker">
                            PERSONNEL MOVEMENT
                        </span>

                        <h2>Daily IN vs OUT</h2>

                        <p>{monthName} {year}</p>
                    </div>

                    <BarChart3 size={20} />
                </div>


                {loading ? (
                    <div className="empty-state">
                        Loading monthly chart...
                    </div>
                ) : chartData.length > 0 ? (

                    <div style={{ width: '100%', height: 320 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                                data={chartData}
                                margin={{
                                    top: 20,
                                    right: 20,
                                    left: 0,
                                    bottom: 10,
                                }}
                            >
                                <CartesianGrid strokeDasharray="3 3" />

                                <XAxis
                                    dataKey="date"
                                    label={{
                                        value: 'Day of month',
                                        position: 'insideBottom',
                                        offset: -5,
                                    }}
                                />

                                <YAxis allowDecimals={false} />

                                <Tooltip />

                                <Legend />

                                <Bar
                                    dataKey="IN"
                                    fill="#14b8a6"
                                    radius={[4, 4, 0, 0]}
                                />

                                <Bar
                                    dataKey="OUT"
                                    fill="#3b82f6"
                                    radius={[4, 4, 0, 0]}
                                />

                            </BarChart>
                        </ResponsiveContainer>
                    </div>

                ) : (
                    <div className="empty-state">
                        <BarChart3 size={24} />

                        <strong>No monthly data available</strong>

                        <span>
                            Entry and exit records will appear after people cross
                            the Gate 3 counting line.
                        </span>
                    </div>
                )}

            </section>


            {/* DAILY TABLE */}

            <section className="panel headcount-events">

                <div className="panel-heading">
                    <div>
                        <span className="section-kicker">
                            DAILY BREAKDOWN
                        </span>

                        <h2>{monthName} {year} Report</h2>
                    </div>

                    <CalendarDays size={20} />
                </div>


                {report?.daily_reports?.length > 0 ? (

                    <div className="table-responsive">

                        <table className="headcount-table">

                            <thead>
                                <tr>
                                    <th>Date</th>
                                    <th>Opening</th>
                                    <th>Total IN</th>
                                    <th>Total OUT</th>
                                    <th>Closing</th>
                                </tr>
                            </thead>

                            <tbody>
                                {report.daily_reports.map(day => (
                                    <tr key={day.report_date}>

                                        <td>
                                            {new Date(
                                                `${day.report_date}T00:00:00`
                                            ).toLocaleDateString('en-IN')}
                                        </td>

                                        <td>{day.opening_count ?? 0}</td>

                                        <td>
                                            <span className="headcount-direction direction-in">
                                                <LogIn size={13} />
                                                {day.total_in ?? 0}
                                            </span>
                                        </td>

                                        <td>
                                            <span className="headcount-direction direction-out">
                                                <LogOut size={13} />
                                                {day.total_out ?? 0}
                                            </span>
                                        </td>

                                        <td>
                                            <strong>{day.closing_count ?? 0}</strong>
                                        </td>

                                    </tr>
                                ))}
                            </tbody>

                        </table>

                    </div>

                ) : (
                    !loading && (
                        <div className="empty-state">
                            No daily records available for this month.
                        </div>
                    )
                )}

            </section>

        </div>
    );
}
