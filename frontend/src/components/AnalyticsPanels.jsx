import { Activity } from 'lucide-react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const tooltipStyle = { background: '#101a23', border: '1px solid #293a46', borderRadius: 8, color: '#e8eef2', fontSize: 12 };

export function DailyActivity({ data = [] }) {
  return <section className="panel chart-panel"><div className="panel-heading"><div><span className="section-kicker">ACTIVITY TREND</span><h2>Daily security events</h2></div><span className="chart-legend"><i className="legend-teal" /> Alerts</span></div>
    <div className="chart-area"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data} margin={{ top: 8, right: 10, left: -18, bottom: 0 }}>
      <defs><linearGradient id="eventFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4bd4c0" stopOpacity={0.27} /><stop offset="95%" stopColor="#4bd4c0" stopOpacity={0} /></linearGradient></defs>
      <CartesianGrid stroke="#23323c" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tick={{ fill: '#7f929d', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fill: '#7f929d', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={tooltipStyle} /><Area type="monotone" dataKey="count" stroke="#4bd4c0" fill="url(#eventFill)" strokeWidth={2} activeDot={{ r: 4, fill: '#7ce8d7' }} />
    </AreaChart></ResponsiveContainer>{!data.length && <div className="chart-empty"><Activity size={17} />Event history will appear here</div>}</div>
  </section>;
}

export function EventBreakdown({ data = [] }) {
  return <section className="panel chart-panel"><div className="panel-heading"><div><span className="section-kicker">EVENT DISTRIBUTION</span><h2>Alert categories</h2></div><span className="period-label">ALL TIME</span></div>
    <div className="chart-area"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
      <CartesianGrid stroke="#23323c" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="name" tick={{ fill: '#7f929d', fontSize: 9 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fill: '#7f929d', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={tooltipStyle} /><Bar dataKey="count" fill="#7996ff" radius={[5, 5, 0, 0]} maxBarSize={42} />
    </BarChart></ResponsiveContainer>{!data.length && <div className="chart-empty"><Activity size={17} />No event data available</div>}</div>
  </section>;
}

export function HourlyActivity({ data = [] }) {
  const hourly = data.map(row => ({ ...row, hour: `${row.hour}:00` }));
  return <section className="panel chart-panel"><div className="panel-heading"><div><span className="section-kicker">TODAY BY HOUR</span><h2>Hourly activity</h2></div><span className="period-label">LOCAL TIME</span></div>
    <div className="chart-area"><ResponsiveContainer width="100%" height="100%"><BarChart data={hourly} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
      <CartesianGrid stroke="#23323c" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="hour" tick={{ fill: '#7f929d', fontSize: 9 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fill: '#7f929d', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={tooltipStyle} /><Bar dataKey="count" fill="#57a7ff" radius={[4, 4, 0, 0]} maxBarSize={26} />
    </BarChart></ResponsiveContainer>{!hourly.length && <div className="chart-empty"><Activity size={17} />No hourly activity yet</div>}</div>
  </section>;
}
