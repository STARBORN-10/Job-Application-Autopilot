import React, { useEffect, useState } from 'react';
import { fetchJobs, updateJob } from '../api';
import { Link } from 'react-router-dom';

const Tracker = () => {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadJobs = async () => {
      try {
        const data = await fetchJobs();
        setJobs(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    loadJobs();
  }, []);

  const handleStatusChange = async (id, newStatus) => {
    try {
      const updated = await updateJob(id, { status: newStatus });
      setJobs(jobs.map(j => j.id === updated.id ? updated : j));
    } catch (err) {
      console.error(err);
    }
  };

  if (loading) {
    return (
      <div className="loader-container">
        <div className="spinner"></div>
      </div>
    );
  }

  const columns = ['To Apply', 'Applied', 'Interview', 'Offer', 'Rejected'];

  return (
    <div>
      <header className="page-header">
        <h1 className="page-title">Application Tracker</h1>
        <p className="page-description">Manage your job application pipeline.</p>
      </header>

      <div className="kanban-board">
        {columns.map(col => {
          const colJobs = jobs.filter(j => j.status === col);
          return (
            <div key={col} className="kanban-column">
              <div className="kanban-header">
                {col} <span className="badge badge-neutral">{colJobs.length}</span>
              </div>
              <div className="kanban-cards">
                {colJobs.map(job => (
                  <div key={job.id} className="kanban-card">
                    <div style={{ fontWeight: '600', marginBottom: '0.25rem' }}>
                      <Link to={`/jobs/${job.id}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                        {job.title}
                      </Link>
                    </div>
                    <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                      {job.company}
                    </div>
                    
                    <select 
                      className="form-control" 
                      style={{ padding: '0.25rem', fontSize: '0.75rem' }}
                      value={job.status}
                      onChange={(e) => handleStatusChange(job.id, e.target.value)}
                    >
                      {columns.map(c => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                ))}
                {colJobs.length === 0 && (
                  <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-muted)', fontSize: '0.875rem', fontStyle: 'italic' }}>
                    No jobs
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default Tracker;
