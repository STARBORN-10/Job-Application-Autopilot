import React, { useEffect, useState } from 'react';
import { Check, ThumbsDown, Info, ShieldCheck } from 'lucide-react';
import { approveJob, fetchApprovePreview, skipJob } from '../api';
import { useToast } from '../context/contexts';
import Modal from './Modal';
import { ErrorState, Spinner } from './Feedback';
import { DecisionBadge } from './Badges';

// Wording used everywhere:
// - "Approve & apply": you want this job; the app prepares (and, only if configured, sends) the application.
// - "Not interested": hide it from your top matches; nothing is sent. Both teach the score weights.
// - The tracker status (To Apply / Applied / Interview / ...) is your own progress and is set separately.
export { DecisionBadge as ApprovalBadge };

const APPROVE_STEPS = ['Saving your decision...', 'Preparing your resume (tailoring can take up to a minute)...',
  'Preparing the application...'];

const ApproveDialog = ({ job, onClose, onDone }) => {
  const { notify } = useToast();
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchApprovePreview(job.id)
      .then((p) => { if (!cancelled) { setPreview(p); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [job.id, reload]);

  useEffect(() => {
    if (!busy) return undefined;
    const t = setInterval(() => setStep((s) => Math.min(s + 1, APPROVE_STEPS.length - 1)), 2500);
    return () => clearInterval(t);
  }, [busy]);

  const confirm = async () => {
    setBusy(true);
    setStep(0);
    setError(null);
    try {
      const res = await approveJob(job.id);
      notify({ type: res.application?.status === 'failed' ? 'error' : 'success', title: 'Approved',
        message: res.message, timeout: 15000 });
      if (res.tailor_error) notify({ type: 'info', title: 'Resume', message: res.tailor_error });
      onDone(res);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Modal title="Approve & apply: what will happen" onClose={onClose} busy={busy}
      footer={(
        <>
          <button type="button" className="btn btn-outline" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={confirm} disabled={busy || !preview}>
            {busy ? <Spinner size={14} label="Approving" /> : <Check size={15} />}
            {busy ? 'Working...' : 'Approve & apply'}
          </button>
        </>
      )}>
      <p className="muted" style={{ marginTop: 0 }}>
        <strong>{job.title}</strong> at {job.company}
      </p>
      {!preview && !error && <div className="inline-loading"><Spinner size={16} /> Checking your settings...</div>}
      {error && <ErrorState title="Problem" message={error} compact onRetry={busy ? undefined : () => setReload((n) => n + 1)} />}
      {preview && (
        <>
          <div className="pill-row">
            {preview.dry_run
              ? <span className="badge badge-warning"><ShieldCheck size={13} /> Dry run: nothing is sent</span>
              : <span className="badge badge-danger">Dry run OFF: e-mails can be sent</span>}
            <span className="badge badge-neutral">
              Method: {preview.method === 'email' ? `e-mail to ${preview.recruiter_email}` : preview.ats ? `${preview.ats} career page` : 'assisted (you submit)'}
            </span>
          </div>
          <ol className="steps-list">
            {preview.steps.map((s) => <li key={s}>{s}</li>)}
          </ol>
          <p className="muted small"><Info size={13} /> Approving also teaches the score weights what you like. You can
            still change the tracker status (Applied, Interview, ...) yourself at any time.</p>
        </>
      )}
      {busy && <div className="inline-loading" aria-live="polite"><Spinner size={16} /> {APPROVE_STEPS[step]}</div>}
    </Modal>
  );
};

// Approve / Not interested buttons. `onChange(job, response)` receives the updated job and the full response.
const ApprovalControls = ({ job, onChange, size = 'md' }) => {
  const { notify } = useToast();
  const [dialog, setDialog] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const status = job.approval_status || 'pending';
  const sm = size === 'sm' ? ' btn-sm' : '';

  const skip = async () => {
    setSkipping(true);
    try {
      const res = await skipJob(job.id);
      notify({ type: 'info', title: 'Marked as not interested', message: res.message });
      onChange?.(res.job, res);
    } catch (err) {
      notify({ type: 'error', title: 'Could not update', message: err.message });
    } finally {
      setSkipping(false);
    }
  };

  return (
    <div className="btn-group">
      <button type="button" className={`btn btn-primary${sm}`} disabled={status === 'approved' || skipping}
        onClick={() => setDialog(true)}
        title={status === 'approved' ? 'Already approved: see the application below' : 'See what will happen, then approve'}>
        <Check size={14} /> {status === 'approved' ? 'Approved' : 'Approve & apply'}
      </button>
      <button type="button" className={`btn btn-outline${sm}`} disabled={status === 'skipped' || skipping}
        onClick={skip} title="Hide from top matches; nothing is sent">
        {skipping ? <Spinner size={13} label="Saving" /> : <ThumbsDown size={14} />}
        {status === 'skipped' ? 'Not interested' : 'Not interested'}
      </button>
      {dialog && (
        <ApproveDialog job={job} onClose={() => setDialog(false)}
          onDone={(res) => { setDialog(false); onChange?.(res.job, res); }} />
      )}
    </div>
  );
};

export default ApprovalControls;
