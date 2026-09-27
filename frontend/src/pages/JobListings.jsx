import React, { useEffect, useState } from 'react';
import { fetchJobs, updateJob } from '../api';
import { Link } from 'react-router-dom';
import { Search, Filter } from 'lucide-react';

const JobListings = () => {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterScore, setFilterScore] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');

  useEffect(() => {
    const loadJobs = async () => {
      try {
        const data = await fetchJobs();
        setJobs(data);
      } catch (err) {
        console.error("Failed to fetch jobs");
      } finally {
        setLoading(false);
      }
    };
    loadJobs();
  }, []);

  const handleApply = async (job) => {
    try {
      const updated = await updateJob(job.id, { status: 'Applied' });
      setJobs(jobs.map(j => j.id === updated.id ? updated : j));
    } catch (e) {
      console.error(e);
    }
  };

  const filteredJobs = jobs.filter(job => {
    const matchesSearch = job.title.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          job.company.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesScore = filterScore === 'all' || 
                         (filterScore === 'high' && job.score >= 8) || 
                         (filterScore === 'medium' && job.score >= 5 && job.score < 8) || 
                         (filterScore === 'low' && job.score < 5);
    const matchesStatus = filterStatus === 'all' || job.status === filterStatus;
    
    return matchesSearch && matchesScore && matchesStatus;
  });

  if (loading) {
    return (
      <div className="loader-container">
        <div className="spinner"></div>
      </div>
    );
  }

  return (
    <div>
      <header className="page-header">
        <h1 className="page-title">Job Listings</h1>
        <p className="page-description">Review discovered jobs and generated applications.</p>
      </header>

      <div className="card" style={{ marginBottom: '1.5rem', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: '250px', position: 'relative' }}>
          <Search size={18} style={{ position: 'absolute', left: '10px', top: '12px', color: 'var(--text-muted)' }} />
          <input 
            type="text" 
            className="form-control" 
            placeholder="Search title or company..." 
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            style={{ paddingLeft: '35px' }}
          />
        </div>
        <select 
          className="form-control" 
          style={{ width: 'auto' }} 
          value={filterScore} 
          onChange={e => setFilterScore(e.target.value)}
        >
          <option value="all">All Scores</option>
          <option value="high">High Match (&ge; 8)</option>
          <option value="medium">Medium Match (5 - 7.9)</option>
          <option value="low">Low Match (&lt; 5)</option>
        </select>
        <select 
          className="form-control" 
          style={{ width: 'auto' }}
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
        >
          <option value="all">All Statuses</option>
          <option value="To Apply">To Apply</option>
          <option value="Applied">Applied</option>
          <option value="Interview">Interview</option>
          <option value="Rejected">Rejected</option>
          <option value="Offer">Offer</option>
        </select>
      </div>

      <div className="job-list">
        {filteredJobs.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
            <p className="text-muted">No jobs found matching your criteria.</p>
          </div>
        ) : (
          filteredJobs.map(job => (
            <div key={job.id} className="job-item card" style={{ padding: '1.5rem' }}>
              <div className="job-info">
                <h3 style={{ marginBottom: '0.5rem' }}>{job.title}</h3>
                <div className="job-meta" style={{ marginBottom: '1rem' }}>
                  <span>{job.company}</span>
                  <span>•</span>
                  <span>{job.location}</span>
                  <span>•</span>
                  <span>{job.job_type}</span>
                  <span>•</span>
                  <span>Score: <strong className={`score-${job.score >= 8 ? 'high' : job.score >= 5 ? 'medium' : 'low'}`}>{job.score}/10</strong></span>
                </div>
                <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1rem', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                  {job.match_reason}
                </p>
                <div>
                   <span className={`badge badge-${job.status === 'Applied' ? 'primary' : job.status === 'To Apply' ? 'warning' : 'neutral'}`}>
                     {job.status}
                   </span>
                </div>
              </div>
              <div className="job-actions" style={{ flexDirection: 'column', gap: '0.5rem', minWidth: '120px' }}>
                {job.status === 'To Apply' && (
                  <button className="btn btn-primary" onClick={() => handleApply(job)}>
                    Mark Applied
                  </button>
                )}
                <Link to={`/jobs/${job.id}`} className="btn btn-outline">
                  View Details
                </Link>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default JobListings;
