import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { fetchJob, updateJob, deleteJob, analyzeJob } from '../api';
import { ArrowLeft, ExternalLink, Trash2, Sparkles } from 'lucide-react';
import ScoreBreakdown from '../components/ScoreBreakdown';

const JobDetails = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);

  useEffect(() => {
    const loadJob = async () => {
      try {
        const data = await fetchJob(id);
        setJob(data);
      } catch (err) {
        console.error("Failed to fetch job", err);
      } finally {
        setLoading(false);
      }
    };
    loadJob();
  }, [id]);

  const handleStatusChange = async (e) => {
    const newStatus = e.target.value;
    try {
      const updated = await updateJob(id, { status: newStatus });
      setJob(updated);
    } catch (err) {
      console.error(err);
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
    if (window.confirm('Are you sure you want to delete this job?')) {
      try {
        await deleteJob(id);
        navigate('/jobs');
      } catch (err) {
        console.error(err);
      }
    }
  };

  if (loading) {
    return (
      <div className="loader-container">
        <div className="spinner"></div>
      </div>
    );
  }

  if (!job) {
    return <div>Job not found</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Link to="/jobs" className="btn btn-outline" style={{ display: 'inline-flex', padding: '0.5rem' }}>
          <ArrowLeft size={20} /> Back to Listings
        </Link>
        <button onClick={handleDelete} className="btn btn-outline" style={{ color: 'var(--danger)', borderColor: 'var(--danger)' }}>
          <Trash2 size={16} /> Delete
        </button>
      </div>

      <div className="card" style={{ marginBottom: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
          <div>
            <h1 className="page-title" style={{ marginBottom: '0.25rem' }}>{job.title}</h1>
            <div style={{ fontSize: '1.125rem', color: 'var(--text-muted)' }}>
              {job.company} • {job.location}
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.75rem' }}>
            <div className={`score-${job.score >= 8 ? 'high' : job.score >= 5 ? 'medium' : 'low'}`} style={{ fontSize: '1.5rem', fontWeight: '700' }}>
              {job.score}/10
            </div>
            <select 
              className="form-control" 
              value={job.status}
              onChange={handleStatusChange}
              style={{ padding: '0.25rem 0.5rem', width: 'auto' }}
            >
              <option value="To Apply">To Apply</option>
              <option value="Applied">Applied</option>
              <option value="Interview">Interview</option>
              <option value="Rejected">Rejected</option>
              <option value="Offer">Offer</option>
            </select>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', padding: '1rem', backgroundColor: 'var(--bg-main)', borderRadius: 'var(--radius-md)', marginBottom: '2rem' }}>
          <div>
            <div className="stat-label">Job Type</div>
            <div style={{ fontWeight: '500' }}>{job.job_type || 'N/A'}</div>
          </div>
          <div>
            <div className="stat-label">Experience</div>
            <div style={{ fontWeight: '500' }}>{job.experience || 'N/A'}</div>
          </div>
          <div>
            <div className="stat-label">Source{job.source_names?.length > 1 ? 's' : ''}</div>
            <div style={{ fontWeight: '500' }}>
              {job.source_names?.length ? job.source_names.join(', ') : job.source || 'N/A'}
            </div>
          </div>
          <div>
            <div className="stat-label">Found On</div>
            <div style={{ fontWeight: '500' }}>{new Date(job.date_found).toLocaleDateString()}</div>
          </div>
        </div>

        <div style={{ marginBottom: '2rem' }}>
          <h3 className="card-title">Match Analysis</h3>
          <div style={{ padding: '1rem', backgroundColor: 'var(--primary)', color: 'white', borderRadius: 'var(--radius-md)', opacity: 0.9 }}>
            {job.match_reason}
          </div>
        </div>

        <div style={{ marginBottom: '2rem' }}>
          <h3 className="card-title">Score Breakdown</h3>
          <ScoreBreakdown breakdown={job.score_breakdown} />
        </div>

        <div style={{ marginBottom: '2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
            <h3 className="card-title" style={{ margin: 0 }}>Resume Fit &amp; Skill Gaps</h3>
            <button className="btn btn-outline" onClick={handleAnalyze} disabled={analyzing}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
              {analyzing ? <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> : <Sparkles size={15} />}
              {analyzing ? 'Analyzing…' : analysis ? 'Re-analyze' : 'Analyze Fit'}
            </button>
          </div>

          {analysisError && (
            <div style={{ marginTop: '0.75rem', color: 'var(--danger)', fontSize: '0.875rem' }}>{analysisError}</div>
          )}

          {analysis && (
            <div style={{ marginTop: '1rem', padding: '1rem', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
              <p style={{ marginTop: 0, lineHeight: 1.6 }}>{analysis.summary}</p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem' }}>
                <div>
                  <div className="stat-label" style={{ color: 'var(--success)' }}>You have</div>
                  <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem', fontSize: '0.875rem', lineHeight: 1.6 }}>
                    {analysis.matched_skills.length ? analysis.matched_skills.map((s, i) => <li key={i}>{s}</li>) : <li>—</li>}
                  </ul>
                </div>
                <div>
                  <div className="stat-label" style={{ color: 'var(--danger)' }}>Missing</div>
                  <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem', fontSize: '0.875rem', lineHeight: 1.6 }}>
                    {analysis.missing_skills.length ? analysis.missing_skills.map((s, i) => <li key={i}>{s}</li>) : <li>—</li>}
                  </ul>
                </div>
                <div>
                  <div className="stat-label" style={{ color: 'var(--primary)' }}>Resume tips</div>
                  <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem', fontSize: '0.875rem', lineHeight: 1.6 }}>
                    {analysis.resume_suggestions.length ? analysis.resume_suggestions.map((s, i) => <li key={i}>{s}</li>) : <li>—</li>}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: '2rem' }}>
          <div style={{ flex: 1 }}>
            <h3 className="card-title">Job Description</h3>
            <div style={{ whiteSpace: 'pre-wrap', color: 'var(--text-muted)', fontSize: '0.875rem', lineHeight: 1.6 }}>
              {job.description}
            </div>
            
            {job.url && (
              <div style={{ marginTop: '2rem' }}>
                <a href={job.url} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
                  View Original Posting <ExternalLink size={16} />
                </a>
              </div>
            )}
          </div>
          
          <div style={{ flex: 1 }}>
            <h3 className="card-title">Generated Cover Letter</h3>
            <div style={{ whiteSpace: 'pre-wrap', padding: '1.5rem', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', backgroundColor: '#fff8f0', fontSize: '0.875rem', lineHeight: 1.6 }}>
              {job.cover_letter || "No cover letter generated yet."}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};

export default JobDetails;
