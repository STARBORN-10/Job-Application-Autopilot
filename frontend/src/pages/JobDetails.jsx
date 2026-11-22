import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, ExternalLink, Trash2, Sparkles } from 'lucide-react';
import { fetchJob, updateJob, deleteJob, analyzeJob } from '../api';
import { usePipeline, useToast } from '../context/contexts';
import ScoreBreakdown from '../components/ScoreBreakdown';
import ApprovalControls from '../components/ApprovalControls';
import ResumeTailorPanel from '../components/ResumeTailorPanel';
import JobApplicationPanel from '../components/JobApplicationPanel';
import { AlsoFoundOn, DecisionBadge, NewTag, ScoreBadge, SourceBadge } from '../components/Badges';
import { CopyButton, ErrorState, PageLoader, Spinner } from '../components/Feedback';
import { formatDate, TRACKER_STATUSES } from '../lib/format';

const List = ({ items }) => (
  <ul className="plain-list">{items?.length ? items.map((s, i) => <li key={i}>{s}</li>) : <li>-</li>}</ul>
);

const JobDetails = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const { newJobIds } = usePipeline();
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const [savingStatus, setSavingStatus] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [panelsKey, setPanelsKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchJob(id)
      .then((data) => { if (!cancelled) { setJob(data); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id, reload]);

  const refreshJob = () => { setReload((n) => n + 1); };

  const handleStatusChange = async (e) => {
    const status = e.target.value;
    setSavingStatus(true);
    try {
      setJob(await updateJob(id, { status }));
      notify({ type: 'success', title: 'Tracker updated', message: `Status set to ${status}.` });
    } catch (err) {
      notify({ type: 'error', title: 'Could not update the status', message: err.message });
    } finally {
      setSavingStatus(false);
    }
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      setAnalysis(await analyzeJob(id));
    } catch (err) {
      setAnalysisError(err.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Delete this job and its application history? This cannot be undone.')) return;
    setDeleting(true);
    try {
      await deleteJob(id);
      notify({ type: 'success', title: 'Deleted', message: 'The job was removed.' });
      navigate('/jobs');
    } catch (err) {
      notify({ type: 'error', title: 'Could not delete', message: err.message });
      setDeleting(false);
    }
  };

  if (loading) return <PageLoader label="Loading job" />;
  if (error || !job) {
    return (
      <div>
        <Link to="/jobs" className="btn btn-outline btn-sm"><ArrowLeft size={16} /> Back to listings</Link>
        <div style={{ marginTop: '1rem' }}>
          {error?.status === 404
            ? <ErrorState title="Job not found" message="It may have been deleted." />
            : <ErrorState title="Could not load this job" message={error?.message} onRetry={refreshJob} />}
        </div>
      </div>
    );
  }

  const afterDecision = (updated) => {
    setJob(updated);
    setPanelsKey((k) => k + 1);
  };

  return (
    <div>
      <div className="page-head">
        <Link to="/jobs" className="btn btn-outline btn-sm"><ArrowLeft size={16} /> Back to listings</Link>
        <button type="button" onClick={handleDelete} className="btn btn-danger btn-sm" disabled={deleting}>
          {deleting ? <Spinner size={13} /> : <Trash2 size={15} />} Delete
        </button>
      </div>

      <section className="card job-hero">
        <div className="job-hero-main">
          <h1 className="page-title job-hero-title">{job.title}</h1>
          <div className="job-hero-sub">{[job.company, job.location].filter(Boolean).join(' · ')}</div>
          <div className="badge-row">
            <SourceBadge source={job.source} url={job.url} />
            <AlsoFoundOn job={job} />
            <DecisionBadge status={job.approval_status} />
            {newJobIds.has(job.id) && <NewTag />}
          </div>
        </div>
        <div className="job-hero-side">
          <ScoreBadge score={job.score} size="lg" />
          <ApprovalControls job={job} onChange={afterDecision} />
          <label className="field-inline">
            <span className="small muted">Your tracker status</span>
            <select className="form-control" value={job.status || 'To Apply'} onChange={handleStatusChange} disabled={savingStatus}>
              {TRACKER_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          {job.url && (
            <a href={job.url} target="_blank" rel="noopener noreferrer" className="btn btn-outline btn-sm">
              <ExternalLink size={14} /> Original posting
            </a>
          )}
        </div>

        <div className="facts-grid">
          <div><div className="stat-label">Job type</div><div>{job.job_type || 'Not stated'}</div></div>
          <div><div className="stat-label">Experience</div><div>{job.experience || 'Not stated'}</div></div>
          <div><div className="stat-label">Found</div><div>{formatDate(job.date_found) || '-'}</div></div>
          <div><div className="stat-label">Last seen</div><div>{formatDate(job.last_seen) || '-'}</div></div>
        </div>
      </section>

      <JobApplicationPanel job={job} refreshKey={panelsKey} onChanged={refreshJob} />
      <ResumeTailorPanel job={job} refreshKey={panelsKey} onChanged={() => setPanelsKey((k) => k + 1)} />

      <section className="card section-card">
        <h2 className="card-title">Why this score</h2>
        {job.match_reason && <p className="match-reason">{job.match_reason}</p>}
        <ScoreBreakdown breakdown={job.score_breakdown} />
      </section>

      <section className="card section-card">
        <div className="section-head">
          <h2 className="card-title">Resume fit &amp; skill gaps (AI)</h2>
          <button type="button" className="btn btn-outline btn-sm" onClick={handleAnalyze} disabled={analyzing}>
            {analyzing ? <Spinner size={13} label="Analyzing" /> : <Sparkles size={14} />}
            {analyzing ? 'Analyzing (up to a minute)...' : analysis ? 'Analyze again' : 'Analyze fit'}
          </button>
        </div>
        {!analysis && !analysisError && !analyzing && (
          <p className="muted small">An AI reading of your active resume next to this posting: what you have, what is missing and resume tips.</p>
        )}
        {analysisError && <ErrorState title="Analysis failed" message={analysisError} compact onRetry={handleAnalyze} />}
        {analysis && (
          <div>
            <p>{analysis.summary}</p>
            <div className="three-col">
              <div><div className="stat-label text-success">You have</div><List items={analysis.matched_skills} /></div>
              <div><div className="stat-label text-danger">Missing</div><List items={analysis.missing_skills} /></div>
              <div><div className="stat-label text-primary">Resume tips</div><List items={analysis.resume_suggestions} /></div>
            </div>
          </div>
        )}
      </section>

      <div className="two-col">
        <section className="card section-card">
          <h2 className="card-title">Job description</h2>
          {job.description
            ? <div className="description-text">{job.description}</div>
            : <p className="muted">No description was provided by the source. Open the original posting.</p>}
          {job.score_breakdown?.description_quality === 'snippet' && (
            <p className="small muted">This source only gives a short snippet; the full text is on the original posting.</p>
          )}
        </section>
        <section className="card section-card">
          <div className="section-head">
            <h2 className="card-title">Cover letter</h2>
            {job.cover_letter && <CopyButton text={job.cover_letter} label="Copy" />}
          </div>
          {job.cover_letter
            ? <div className="letter-box">{job.cover_letter}</div>
            : <p className="muted">No cover letter yet. One is written by the AI when you approve the job (if an AI provider is configured).</p>}
        </section>
      </div>
    </div>
  );
};

export default JobDetails;
