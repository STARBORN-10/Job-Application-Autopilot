import React, { useEffect, useState } from 'react';
import { fetchJobs, triggerAutomation, fetchGeneralSettings } from '../api';
import { Briefcase, CheckCircle, Clock, Star, Target, Sparkles, RefreshCw, AlertCircle } from 'lucide-react';
import { Link } from 'react-router-dom';

const Dashboard = () => {
  const [jobs, setJobs] = useState([]);
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [triggerAlert, setTriggerAlert] = useState(null);

  const loadData = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const [jobsData, settingsData] = await Promise.all([
        fetchJobs(),
        fetchGeneralSettings().catch(() => null),
      ]);
      setJobs(jobsData);
      if (settingsData) setSettings(settingsData);
    } catch (err) {
      console.error("Failed to fetch dashboard data", err);
    } finally {
      setLoading(false);
      if (isRefresh) setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleTriggerAutomation = async () => {
    setTriggering(true);
    setTriggerAlert(null);
    try {
      const res = await triggerAutomation();
      setTriggerAlert({
        type: 'success',
        message: res.message || 'Make.com job search triggered! Fresh matching opportunities will appear as they are processed.',
      });
      // Auto reload after 4 seconds
      setTimeout(() => loadData(true), 4000);
    } catch (err) {
      setTriggerAlert({
        type: 'error',
        message: err.message || 'Failed to trigger Make.com webhook.',
        needsConfig: err.message?.includes('not configured'),
      });
    } finally {
      setTriggering(false);
    }
  };

  if (loading) {
    return (
      <div className="loader-container">
        <div className="spinner"></div>
      </div>
    );
  }

  const minScore = settings?.min_match_score || 7.0;
  const goodMatches = jobs.filter(j => j.score >= minScore);
  const toApply = jobs.filter(j => j.status === 'To Apply');
  const applied = jobs.filter(j => j.status !== 'To Apply' && j.status !== 'Rejected');
  const avgScore = jobs.length ? (jobs.reduce((acc, j) => acc + (j.score || 0), 0) / jobs.length).toFixed(1) : '0.0';

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.5rem' }}>
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>Dashboard</h1>
          <p className="page-description" style={{ marginTop: '0.25rem' }}>
            Overview of your automated job hunting {settings?.active_role ? `for ${settings.active_role}` : ''}.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            className="btn btn-outline"
            onClick={() => loadData(true)}
            disabled={refreshing}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
            title="Refresh jobs from database"
          >
            <RefreshCw size={15} className={refreshing ? 'spinner' : ''} />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>

          <button
            className="btn btn-primary"
            onClick={handleTriggerAutomation}
            disabled={triggering}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', boxShadow: '0 2px 8px rgba(79, 70, 229, 0.25)' }}
          >
            {triggering ? <span className="spinner" style={{ width: 15, height: 15, borderWidth: 2 }} /> : <Sparkles size={16} />}
            {triggering ? 'Triggering Make.com…' : 'Find New Jobs'}
          </button>
        </div>
      </div>

      {triggerAlert && (
        <div style={{
          backgroundColor: triggerAlert.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
          color: triggerAlert.type === 'success' ? 'var(--success)' : 'var(--danger)',
          border: `1px solid ${triggerAlert.type === 'success' ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)'}`,
          padding: '0.85rem 1.25rem',
          borderRadius: 'var(--radius-md)',
          marginBottom: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1rem',
          animation: 'fadeIn 0.2s ease',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {triggerAlert.type === 'success' ? <CheckCircle size={18} /> : <AlertCircle size={18} />}
            <span>{triggerAlert.message}</span>
          </div>
          {triggerAlert.needsConfig && (
            <Link to="/settings" className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.3rem 0.6rem' }}>
              Configure in Settings
            </Link>
          )}
        </div>
      )}

      <div className="grid-stats">
        <div className="card stat-card">
          <div className="stat-label">Total Jobs Found</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Briefcase size={28} color="var(--primary)" />
            {jobs.length}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Good Matches (&ge; {minScore})</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Target size={28} color="var(--success)" />
            {goodMatches.length}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">To Apply</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Clock size={28} color="var(--warning)" />
            {toApply.length}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Applications Sent</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <CheckCircle size={28} color="var(--primary)" />
            {applied.length}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Avg. Match Score</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Star size={28} color="var(--warning)" fill="var(--warning)" />
            {avgScore}
          </div>
        </div>
      </div>

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2 className="card-title" style={{ margin: 0 }}>Top Matching Opportunities</h2>
          <Link to="/jobs" style={{ fontSize: '0.85rem', color: 'var(--primary)', textDecoration: 'none', fontWeight: 500 }}>
            View All Jobs &rarr;
          </Link>
        </div>
        <div className="job-list">
          {goodMatches.slice(0, 5).map(job => (
            <div key={job.id} className="job-item">
              <div className="job-info">
                <h3>{job.title}</h3>
                <div className="job-meta">
                  <span>{job.company}</span>
                  <span>•</span>
                  <span>{job.location || 'Remote'}</span>
                  <span>•</span>
                  <span>{job.experience || 'Fresher / Entry'}</span>
                </div>
              </div>
              <div className="job-actions" style={{ alignItems: 'center' }}>
                <div className={`score-${job.score >= 8 ? 'high' : job.score >= 5 ? 'medium' : 'low'}`} style={{ fontWeight: 'bold', marginRight: '1rem' }}>
                  {job.score}/10 Match
                </div>
                <Link to={`/jobs/${job.id}`} className="btn btn-outline">View Details</Link>
              </div>
            </div>
          ))}
          {goodMatches.length === 0 && (
            <div style={{ textAlign: 'center', padding: '2rem 1rem', color: 'var(--text-muted)' }}>
              <p style={{ margin: '0 0 0.5rem 0' }}>No high match jobs found yet.</p>
              <p style={{ fontSize: '0.85rem', margin: 0 }}>
                Click <strong>"Find New Jobs"</strong> above or configure your search in Settings to start discovering jobs.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
