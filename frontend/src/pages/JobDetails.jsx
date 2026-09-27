import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { fetchJob, updateJob, deleteJob } from '../api';
import { ArrowLeft, ExternalLink, Trash2 } from 'lucide-react';

const JobDetails = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);

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
            <div className="stat-label">Source</div>
            <div style={{ fontWeight: '500' }}>{job.source || 'N/A'}</div>
          </div>
          <div>
            <div className="stat-label">Found On</div>
            <div style={{ fontWeight: '500' }}>{new Date(job.date_found).toLocaleDateString()}</div>
          </div>
        </div>

        <div style={{ marginBottom: '2rem' }}>
          <h3 className="card-title">AI Match Analysis</h3>
          <div style={{ padding: '1rem', backgroundColor: 'var(--primary)', color: 'white', borderRadius: 'var(--radius-md)', opacity: 0.9 }}>
            {job.match_reason}
          </div>
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
