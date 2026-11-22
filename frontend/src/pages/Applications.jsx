import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { fetchApplications, fetchApplicationsConfig, retryApplication } from '../api';
import { useToast } from '../context/contexts';
import { ApplicationRecord } from '../components/JobApplicationPanel';
import { SourceBadge } from '../components/Badges';
import { ErrorState, PageLoader, Spinner } from '../components/Feedback';

export const DryRunBanner = ({ config }) => {
  if (!config?.dry_run) return null;
  return (
    <div className="alert alert-warning">
      <AlertTriangle size={18} className="alert-icon" aria-hidden="true" />
      <div className="alert-body">
        <strong>Dry run is on.</strong> Approved jobs are logged here with what would be sent, but no e-mail leaves the
        server and no form is submitted. Set <code>APPLY_DRY_RUN=false</code> (and the SMTP settings) on the backend to
        send e-mails for real.
      </div>
    </div>
  );
};

const FILTERS = [
  ['all', 'All'], ['email', 'E-mail'], ['assisted', 'Assisted'], ['autofill', 'Form pre-fill'], ['problems', 'Needs attention'],
];

const Applications = () => {
  const { notify } = useToast();
  const [rows, setRows] = useState([]);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const [filter, setFilter] = useState('all');
  const [retrying, setRetrying] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchApplications(), fetchApplicationsConfig().catch(() => null)])
      .then(([apps, cfg]) => { if (!cancelled) { setRows(apps); setConfig(cfg); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reload]);

  const retry = async (jobId) => {
    setRetrying(jobId);
    try {
      const res = await retryApplication(jobId);
      notify({ type: res.status === 'failed' ? 'error' : 'success', title: 'Apply step re-run', message: res.outcome });
      setReload((n) => n + 1);
    } catch (err) {
      notify({ type: 'error', title: 'Could not retry', message: err.message });
    } finally {
      setRetrying(null);
    }
  };

  if (loading) return <PageLoader label="Loading applications" />;

  const visible = rows.filter((a) => {
    if (filter === 'all') return true;
    if (filter === 'problems') return ['failed', 'needs_input', 'skipped'].includes(a.status);
    return a.method === filter;
  });

  return (
    <div>
      <div className="page-head">
        <div className="page-head-text">
          <h1 className="page-title">Applications</h1>
          <p className="page-description">
            Everything prepared or sent after you approved a job: e-mails to recruiters (dry run unless enabled), assisted
            applications you submit yourself, and pre-filled career-page forms.
          </p>
        </div>
        <button type="button" className="btn btn-outline" onClick={() => setReload((n) => n + 1)}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      <DryRunBanner config={config} />
      {config && (
        <p className="small muted">
          E-mails today: {config.emails_today}/{config.daily_cap} · SMTP {config.smtp_configured ? 'configured' : 'not configured'}
        </p>
      )}
      {error && <ErrorState title="Could not load applications" message={error} onRetry={() => setReload((n) => n + 1)} />}

      <div className="seg" role="tablist" aria-label="Filter applications">
        {FILTERS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={filter === key} className={filter === key ? 'seg-on' : ''}
            onClick={() => setFilter(key)}>{label}</button>
        ))}
      </div>

      {visible.length === 0 ? (
        <div className="card empty-state">
          <p><strong>{rows.length ? 'Nothing in this filter.' : 'No applications yet.'}</strong></p>
          <p className="muted small">Approve a job (dashboard, job page or Telegram) to prepare its application.</p>
        </div>
      ) : (
        <div className="job-list">
          {visible.map((a) => (
            <article key={a.id} className="card app-card">
              <div className="section-head">
                <div className="min0">
                  <h3 className="app-title"><Link to={`/jobs/${a.job_id}`}>{a.job_title || `Job #${a.job_id}`}</Link></h3>
                  <div className="badge-row"><span className="muted small">{a.job_company}</span>
                    {a.job_source && <SourceBadge source={a.job_source} url={a.job_url} />}</div>
                </div>
                {['failed', 'skipped'].includes(a.status) && a.method !== 'autofill' && (
                  <button type="button" className="btn btn-outline btn-sm" onClick={() => retry(a.job_id)} disabled={retrying === a.job_id}>
                    {retrying === a.job_id ? <Spinner size={13} /> : <RefreshCw size={14} />} Retry
                  </button>
                )}
              </div>
              <ApplicationRecord a={a} job={{ id: a.job_id, url: a.job_url, cover_letter: a.cover_letter }} />
            </article>
          ))}
        </div>
      )}
    </div>
  );
};

export default Applications;
