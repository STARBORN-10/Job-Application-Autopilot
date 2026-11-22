import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchJobs, updateJob } from '../api';
import { usePipeline, useToast } from '../context/contexts';
import { DecisionBadge, ScoreBadge, SourceBadge } from '../components/Badges';
import { ErrorState, PageLoader } from '../components/Feedback';
import { TRACKER_STATUSES } from '../lib/format';

const Tracker = () => {
  const { notify } = useToast();
  const { jobsVersion } = usePipeline();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const [hideSkipped, setHideSkipped] = useState(true);
  const [saving, setSaving] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchJobs()
      .then((data) => { if (!cancelled) { setJobs(data); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reload, jobsVersion]);

  const handleStatusChange = async (job, status) => {
    setSaving(job.id);
    try {
      const updated = await updateJob(job.id, { status });
      setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
    } catch (err) {
      notify({ type: 'error', title: 'Could not move the job', message: err.message });
    } finally {
      setSaving(null);
    }
  };

  if (loading) return <PageLoader label="Loading your tracker" />;

  const visible = jobs.filter((j) => !(hideSkipped && j.approval_status === 'skipped' && (j.status || 'To Apply') === 'To Apply'));

  return (
    <div>
      <div className="page-head">
        <div className="page-head-text">
          <h1 className="page-title">Application tracker</h1>
          <p className="page-description">
            Your own progress for each job. Approving prepares an application; a sent e-mail moves the job to Applied
            automatically, everything else you move here yourself.
          </p>
        </div>
        <label className="check-label">
          <input type="checkbox" checked={hideSkipped} onChange={(e) => setHideSkipped(e.target.checked)} />
          Hide "Not interested" jobs
        </label>
      </div>
      {error && <ErrorState title="Could not load jobs" message={error} onRetry={() => setReload((n) => n + 1)} />}

      <div className="kanban-board">
        {TRACKER_STATUSES.map((col) => {
          const colJobs = visible.filter((j) => (j.status || 'To Apply') === col);
          return (
            <section key={col} className="kanban-column" aria-label={col}>
              <div className="kanban-header">
                {col} <span className="badge badge-neutral">{colJobs.length}</span>
              </div>
              <div className="kanban-cards">
                {colJobs.map((job) => (
                  <div key={job.id} className="kanban-card">
                    <div className="kanban-title">
                      <Link to={`/jobs/${job.id}`}>{job.title}</Link>
                      <ScoreBadge score={job.score} size="sm" />
                    </div>
                    <div className="muted small kanban-company">{job.company}</div>
                    <div className="badge-row">
                      <SourceBadge source={job.source} url={job.url} />
                      {job.approval_status !== 'pending' && <DecisionBadge status={job.approval_status} />}
                    </div>
                    <select className="form-control form-control-sm" value={job.status || 'To Apply'} disabled={saving === job.id}
                      onChange={(e) => handleStatusChange(job, e.target.value)} aria-label={`Status of ${job.title}`}>
                      {TRACKER_STATUSES.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                ))}
                {colJobs.length === 0 && <div className="kanban-empty">No jobs</div>}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
};

export default Tracker;
