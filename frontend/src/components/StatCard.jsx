export default function StatCard({ title, value, icon: Icon, tone, subtitle }) {
  return <article className="stat-card">
    <div className="stat-info"><p>{title}</p><strong>{value ?? '--'}</strong><span>{subtitle}</span></div>
    <div className={`stat-icon ${tone}`}><Icon size={19} /></div>
  </article>;
}
