import React, { useState } from 'react';
import { Check, X } from 'lucide-react';
import { approveJob, skipJob } from '../api';

const BADGE = { approved: 'badge-success', skipped: 'badge-neutral', pending: 'badge-warning' };

export const ApprovalBadge = ({ status }) => {
  const s = status || 'pending';
  return <span className={`badge ${BADGE[s] || 'badge-neutral'}`}>{s === 'pending' ? 'Awaiting decision' : s}</span>;
};

// Approve / Skip buttons. `onChange(job, application)` receives the updated job.
const ApprovalControls = ({ job, onChange, compact = false }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const status = job.approval_status || 'pending';

  const decide = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fn(job.id);
      onChange?.(res.job, res.application);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const style = { display: 'inline-flex', alignItems: 'center', gap: 4, padding: compact ? '0.35rem 0.6rem' : undefined };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="btn btn-primary" style={style} disabled={busy || status === 'approved'}
          onClick={() => decide(approveJob)} title="Approve this job (same as the Telegram button)">
          <Check size={14} /> {status === 'approved' ? 'Approved' : 'Approve'}
        </button>
        <button className="btn btn-outline" style={style} disabled={busy || status === 'skipped'}
          onClick={() => decide(skipJob)}>
          <X size={14} /> {status === 'skipped' ? 'Skipped' : 'Skip'}
        </button>
      </div>
      {error && <span style={{ color: 'var(--danger)', fontSize: '0.75rem' }}>{error}</span>}
    </div>
  );
};

export default ApprovalControls;
