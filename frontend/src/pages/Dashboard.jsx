import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Briefcase, CheckCircle, Clock, Star, Target, RefreshCw } from 'lucide-react';
import { fetchJobs, fetchTopJobs, fetchGeneralSettings } from '../api';
import { usePipeline } from '../context/contexts';
import FindJobsButton from '../components/FindJobsButton';
import PipelineProgress from '../components/PipelineProgress';
import JobCard from '../components/JobCard';
import { ErrorState, PageLoader, Spinner } from '../components/Feedback';

const TOP_COUNT = 5;

const Dashboard = () => {
  const { jobsVersion, newJobIds } = usePipeline();
  const [jobs, setJobs] = useState([]);
  const [top, setTop] = useState([]);
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Reload on mount, on Refresh, and whenever the running job search saves new jobs.
  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchJobs(), fetchTopJobs(TOP_COUNT), fetchGeneralSettings().catch(() => null)])
      .then(([all, best, s]) => {
        if (cancelled) return;
        setJobs(all);
        setTop(best);
        if (s) setSettings(s);
        setError(null);
      })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) { setLoading(false); setRefreshing(false); } });
    return () => { cancelled = true; };
  }, [reloadKey, jobsVersion]);

  const refresh = () => { setRefreshing(true); setReloadKey((k) => k + 1); };
  const replaceJob = (updated) => {
    setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
    setReloadKey((k) => k + 1); // a decision can change the top list (skipped jobs drop out)
  };

  if (loading) return <PageLoader label="Loading your dashboard" />;

  const minScore = settings?.min_match_score ?? 7.0;
  const scored = jobs.filter((j) => typeof j.score === 'number');
  const goodMatches = scored.filter((j) => j.score >= minScore);
  const toApply = jobs.filter((j) => (j.status || 'To Apply') === 'To Apply' && j.approval_status !== 'skipped');
  const appliedOrLater = jobs.filter((j) => ['Applied', 'Interview', 'Offer'].includes(j.status));
  const avgScore = scored.length ? (scored.reduce((acc, j) => acc + j.score, 0) / scored.length).toFixed(1) : '-';
  const newCount = jobs.filter((j) => newJobIds.has(j.id)).length;

  const stats = [
    ['Jobs found', jobs.length, Briefcase, 'var(--primary)', newCount ? `${newCount} new in the latest search` : null],
    [`Good matches (score ≥ ${minScore})`, goodMatches.length, Target, 'var(--success)', null],
    ['To apply', toApply.length, Clock, 'var(--warning)', 'Not applied yet and not skipped'],
    ['Applied or further', appliedOrLater.length, CheckCircle, 'var(--primary)', 'Applied, Interview or Offer'],
    ['Average score', avgScore, Star, 'var(--warning)', null],
  ];

  return (
    <div>
      <div className="page-head">
        <div className="page-head-text">
          <h1 className="page-title">Dashboard</h1>
          <p className="page-description">
            Your job search at a glance{settings?.active_role ? ` for ${settings.active_role}` : ''}.
          </p>
        </div>
        <div className="btn-group">
          <button type="button" className="btn btn-outline" onClick={refresh} disabled={refreshing}
            title="Reload jobs from the database">
            {refreshing ? <Spinner size={14} label="Refreshing" /> : <RefreshCw size={15} />}
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <FindJobsButton />
        </div>
      </div>

      <PipelineProgress />
      {error && <ErrorState title="Could not load your jobs" message={error} onRetry={refresh} />}

      <div className="grid-stats">
        {stats.map(([label, value, Icon, color, hint]) => (
          <div key={label} className="card stat-card">
            <div className="stat-label">{label}</div>
            <div className="stat-value"><Icon size={26} color={color} aria-hidden="true" /> {value}</div>
            {hint && <div className="stat-hint">{hint}</div>}
          </div>
        ))}
      </div>

      <section className="card">
        <div className="section-head">
          <div>
            <h2 className="card-title">Top matching opportunities</h2>
            <p className="muted small">Highest score first (ties: newest). Jobs you marked "Not interested" or Rejected are hidden.</p>
          </div>
          <Link to="/jobs" className="link-more">View all jobs &rarr;</Link>
        </div>
        <div className="job-list">
          {top.map((job) => (
            <JobCard key={job.id} job={job} variant="compact" isNew={newJobIds.has(job.id)} onChange={replaceJob} />
          ))}
          {top.length === 0 && !error && (
            <div className="empty-state">
              <p><strong>No scored jobs yet.</strong></p>
              <p className="muted small">Click <strong>Find New Jobs</strong> to search every enabled source, or check your
                resume and sources in <Link to="/settings">Settings</Link>.</p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default Dashboard;
