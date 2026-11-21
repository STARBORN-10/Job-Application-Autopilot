import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Copy, Check, ExternalLink, RefreshCw, Mail, MousePointerClick } from 'lucide-react';
import { fetchApplications, fetchApplicationsConfig, retryApplication } from '../api';

const STATUS_BADGE = {
  sent: 'badge-success',
  dry_run: 'badge-primary',
  ready_to_submit: 'badge-warning',
  failed: 'badge-danger',
  skipped: 'badge-neutral',
};

export const DryRunBanner = ({ config }) => {
  if (!config?.dry_run) return null;
  return (
    <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start', padding: '0.85rem 1.1rem', marginBottom: '1.5rem',
      borderRadius: 'var(--radius-md)', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)',
      color: '#92400e', fontSize: '0.875rem' }}>
      <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 1 }} />
      <span>
        <strong>Dry run is on.</strong> Approved jobs are logged here with what would be sent, but no e-mail leaves the
        server. Set <code>APPLY_DRY_RUN=false</code> (and the SMTP settings) on the backend to send for real.
      </span>
    </div>
  );
};

const CopyButton = ({ text }) => {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button type="button" className="btn btn-outline" onClick={copy} style={{ display: 'inline-flex', gap: 4, alignItems: 'center', padding: '0.35rem 0.6rem' }}>
      {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy cover letter'}
    </button>
  );
};

const fmt = (iso) => (iso ? new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).toLocaleString() : '');

const Applications = () => {
  const [rows, setRows] = useState([]);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      const [apps, cfg] = await Promise.all([fetchApplications(), fetchApplicationsConfig()]);
      setRows(apps);
      setConfig(cfg);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    Promise.all([fetchApplications(), fetchApplicationsConfig()])
      .then(([apps, cfg]) => {
        setRows(apps);
        setConfig(cfg);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const retry = async (jobId) => {
    try {
      await retryApplication(jobId);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) {
    return <div className="loader-container"><div className="spinner"></div></div>;
  }

  return (
    <div>
      <header className="page-header">
        <h1 className="page-title">Applications</h1>
        <p className="page-description">
          Every apply attempt after you approve a job. E-mail applications go to the recruiter address found in the
          posting; everything else is "assisted": open the link and submit with the prepared cover letter.
        </p>
      </header>

      <DryRunBanner config={config} />
      {config && (
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
          E-mails today: {config.emails_today}/{config.daily_cap} · SMTP {config.smtp_configured ? 'configured' : 'not configured'}
        </div>
      )}
      {error && <div style={{ color: 'var(--danger)', marginBottom: '1rem' }}>{error}</div>}

      {rows.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
          <p className="text-muted">No applications yet. Approve a job (dashboard or Telegram) to start one.</p>
        </div>
      ) : (
        <div className="job-list">
          {rows.map((a) => (
            <div key={a.id} className="card" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                  <h3 style={{ marginBottom: '0.35rem', fontSize: '1rem' }}>
                    <Link to={`/jobs/${a.job_id}`}>{a.job_title || `Job #${a.job_id}`}</Link>
                    <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}> · {a.job_company}</span>
                  </h3>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap', fontSize: '0.8rem' }}>
                    <span className="badge badge-neutral" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                      {a.method === 'email' ? <Mail size={12} /> : <MousePointerClick size={12} />} {a.method}
                    </span>
                    <span className={`badge ${STATUS_BADGE[a.status] || 'badge-neutral'}`}>{a.status.replace(/_/g, ' ')}</span>
                    {a.dry_run && <span className="badge badge-primary">dry run</span>}
                    <span style={{ color: 'var(--text-muted)' }}>{fmt(a.created_at)}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                  {a.job_url && (
                    <a href={a.job_url} target="_blank" rel="noopener noreferrer" className="btn btn-outline"
                      style={{ display: 'inline-flex', gap: 4, alignItems: 'center', padding: '0.35rem 0.6rem' }}>
                      <ExternalLink size={14} /> Open posting
                    </a>
                  )}
                  {a.method === 'assisted' && a.cover_letter && <CopyButton text={a.cover_letter} />}
                  {(a.status === 'failed' || a.status === 'skipped') && (
                    <button type="button" className="btn btn-outline" onClick={() => retry(a.job_id)}
                      style={{ display: 'inline-flex', gap: 4, alignItems: 'center', padding: '0.35rem 0.6rem' }}>
                      <RefreshCw size={14} /> Retry
                    </button>
                  )}
                </div>
              </div>
              <div style={{ marginTop: '0.6rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                {a.method === 'email' && a.payload_summary?.to && (
                  <div>To: {a.payload_summary.to} · Subject: {a.payload_summary.subject} · Attachment: {a.payload_summary.attachment || 'none'}</div>
                )}
                {a.payload_summary?.note && <div>{a.payload_summary.note}</div>}
                {a.payload_summary?.telegram_sent && <div>Link and cover letter sent to Telegram.</div>}
                {a.error && <div style={{ color: 'var(--danger)' }}>Error: {a.error}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default Applications;
