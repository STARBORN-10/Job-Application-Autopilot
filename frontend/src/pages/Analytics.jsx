import React, { useEffect, useState } from 'react';
import { fetchAnalytics } from '../api';
import { Briefcase, Star, Send, TrendingUp } from 'lucide-react';

const STATUS_COLORS = {
  'To Apply': 'var(--warning)',
  Applied: 'var(--primary)',
  Interview: '#0ea5e9',
  Offer: 'var(--success)',
  Rejected: 'var(--danger)',
};

const BAR_TRACK = { background: 'var(--bg-main)', borderRadius: 999, height: 10, overflow: 'hidden', flex: 1 };

// Horizontal bar list: [{label, count}] -> proportional bars.
const BarList = ({ rows, colorFor }) => {
  const max = Math.max(1, ...rows.map(r => r.count));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
      {rows.map(r => (
        <div key={r.label} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ width: 110, fontSize: '0.85rem', color: 'var(--text-muted)', flexShrink: 0 }}>{r.label}</div>
          <div style={BAR_TRACK}>
            <div style={{
              width: `${(r.count / max) * 100}%`, height: '100%',
              background: colorFor ? colorFor(r.label) : 'var(--primary)', transition: 'width 0.3s ease',
            }} />
          </div>
          <div style={{ width: 32, textAlign: 'right', fontWeight: 600, fontSize: '0.9rem' }}>{r.count}</div>
        </div>
      ))}
    </div>
  );
};

// Vertical columns for jobs-per-day timeline.
const Timeline = ({ points }) => {
  const max = Math.max(1, ...points.map(p => p.count));
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 120 }}>
        {points.map(p => (
          <div
            key={p.date}
            title={`${p.date}: ${p.count} job${p.count === 1 ? '' : 's'}`}
            style={{
              flex: 1, minHeight: 2, height: `${(p.count / max) * 100}%`,
              background: p.count ? 'var(--primary)' : 'var(--border)', borderRadius: '3px 3px 0 0',
            }}
          />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 6 }}>
        <span>{points[0]?.date}</span>
        <span>{points[points.length - 1]?.date}</span>
      </div>
    </div>
  );
};

const Analytics = () => {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchAnalytics(days)
      .then(d => { if (!cancelled) { setData(d); setError(null); } })
      .catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [days]);

  if (error) {
    return <div className="card" style={{ color: 'var(--danger)' }}>Could not load analytics: {error}</div>;
  }
  if (!data) {
    return <div className="loader-container"><div className="spinner"></div></div>;
  }

  const stat = (label, value, Icon, color) => (
    <div className="card stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Icon size={28} color={color} />
        {value}
      </div>
    </div>
  );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.5rem' }}>
        <header className="page-header" style={{ margin: 0 }}>
          <h1 className="page-title">Analytics</h1>
          <p className="page-description">How your job search is progressing.</p>
        </header>
        <select className="form-control" style={{ width: 'auto' }} value={days} onChange={e => setDays(Number(e.target.value))}>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="grid-stats">
        {stat('Total Jobs', data.total_jobs, Briefcase, 'var(--primary)')}
        {stat('Average Match Score', data.average_score, Star, 'var(--warning)')}
        {stat('Application Rate', `${data.application_rate}%`, Send, 'var(--success)')}
        {stat('Interview Rate', `${data.interview_rate}%`, TrendingUp, '#0ea5e9')}
      </div>

      {data.total_jobs === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem', marginTop: '1.5rem' }}>
          <p className="text-muted">No jobs yet. Run “Find New Jobs” on the Dashboard to start collecting data.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '1.5rem', marginTop: '1.5rem' }}>
          <div className="card">
            <h3 className="card-title">Application Funnel</h3>
            <BarList
              rows={data.funnel.map(f => ({ label: f.status, count: f.count }))}
              colorFor={label => STATUS_COLORS[label] || 'var(--primary)'}
            />
          </div>

          <div className="card">
            <h3 className="card-title">Match Score Distribution</h3>
            <BarList
              rows={data.score_distribution.map(s => ({ label: s.range, count: s.count }))}
              colorFor={label => (label === '9-10' || label === '7-8' ? 'var(--success)' : label === '5-6' ? 'var(--warning)' : 'var(--danger)')}
            />
          </div>

          <div className="card" style={{ gridColumn: '1 / -1' }}>
            <h3 className="card-title">Jobs Found (last {days} days)</h3>
            <Timeline points={data.jobs_over_time} />
          </div>

          <div className="card">
            <h3 className="card-title">Top Companies</h3>
            <BarList rows={data.top_companies.map(c => ({ label: c.company, count: c.count }))} />
          </div>

          <div className="card">
            <h3 className="card-title">Sources</h3>
            <BarList rows={data.sources.map(s => ({ label: s.source, count: s.count }))} />
          </div>
        </div>
      )}
    </div>
  );
};

export default Analytics;
