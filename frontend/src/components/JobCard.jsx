import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckSquare, ExternalLink } from 'lucide-react';
import { updateJob } from '../api';
import { useToast } from '../context/contexts';
import ApprovalControls from './ApprovalControls';
import { AlsoFoundOn, DecisionBadge, NewTag, ScoreBadge, SourceBadge, StatusBadge } from './Badges';
import { ScoreBreakdownCompact } from './ScoreBreakdown';
import { Spinner } from './Feedback';

// One job in a list. Layout: details on the left (shrinks, long text wraps / truncates), score and
// actions on the right; stacks into one column on narrow screens so no button is ever clipped.
const JobCard = ({ job, isNew = false, onChange, variant = 'full' }) => {
  const { notify } = useToast();
  const [marking, setMarking] = useState(false);
  const full = variant === 'full';

  const markApplied = async () => {
    setMarking(true);
    try {
      const updated = await updateJob(job.id, { status: 'Applied' });
      notify({ type: 'success', title: 'Tracker updated', message: `"${job.title}" is now marked as Applied.` });
      onChange?.(updated);
    } catch (err) {
      notify({ type: 'error', title: 'Could not update the tracker', message: err.message });
    } finally {
      setMarking(false);
    }
  };

  const meta = [job.company, job.location, full ? job.job_type : null, job.experience].filter(Boolean);

  return (
    <article className={`job-card${isNew ? ' job-card-new' : ''}`}>
      <div className="job-card-main">
        <div className="job-card-title-row">
          <Link to={`/jobs/${job.id}`} className="job-title" title={job.title}>{job.title}</Link>
          {isNew && <NewTag />}
        </div>
        <div className="job-meta" title={meta.join(' · ')}>
          {meta.map((m, i) => <span key={i} className={i === 0 ? 'job-company' : undefined}>{m}</span>)}
        </div>
        <div className="badge-row">
          <SourceBadge source={job.source} url={job.url} />
          <AlsoFoundOn job={job} compact={!full} />
          <StatusBadge status={job.status} />
          <DecisionBadge status={job.approval_status} />
        </div>
        {full && <ScoreBreakdownCompact breakdown={job.score_breakdown} />}
        {full && job.match_reason && <p className="job-reason">{job.match_reason}</p>}
      </div>
      <div className="job-card-side">
        <ScoreBadge score={job.score} />
        <div className="job-card-actions">
          {full && <ApprovalControls job={job} size="sm" onChange={(updated) => onChange?.(updated)} />}
          <div className="btn-group">
            {full && job.status === 'To Apply' && (
              <button type="button" className="btn btn-outline btn-sm" onClick={markApplied} disabled={marking}
                title="You applied on your own: move it to Applied in the tracker">
                {marking ? <Spinner size={13} label="Saving" /> : <CheckSquare size={14} />} I applied
              </button>
            )}
            {!full && job.url && (
              <a href={job.url} target="_blank" rel="noopener noreferrer" className="btn btn-outline btn-sm"
                aria-label={`Open the original posting for ${job.title}`}>
                <ExternalLink size={14} /> Posting
              </a>
            )}
            <Link to={`/jobs/${job.id}`} className="btn btn-outline btn-sm">Details</Link>
          </div>
        </div>
      </div>
    </article>
  );
};

export default JobCard;
