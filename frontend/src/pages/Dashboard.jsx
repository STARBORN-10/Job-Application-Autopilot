import React, { useEffect, useState } from 'react';
import { fetchJobs } from '../api';
import { Briefcase, CheckCircle, Clock, Star, Target } from 'lucide-react';
import { Link } from 'react-router-dom';

const Dashboard = () => {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

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

  if (loading) {
    return (
      <div className="loader-container">
        <div className="spinner"></div>
      </div>
    );
  }

  const goodMatches = jobs.filter(j => j.score >= 8);
  const toApply = jobs.filter(j => j.status === 'To Apply');
  const applied = jobs.filter(j => j.status !== 'To Apply' && j.status !== 'Rejected');
  const avgScore = jobs.length ? (jobs.reduce((acc, j) => acc + j.score, 0) / jobs.length).toFixed(1) : 0;

  return (
    <div>
      <header className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-description">Overview of your automated job hunting.</p>
      </header>

      <div className="grid-stats">
        <div className="card stat-card">
          <div className="stat-label">Total Jobs Found</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Briefcase size={28} color="var(--primary)" />
            {jobs.length}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Good Matches</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Target size={28} color="var(--success)" />
            {goodMatches.length}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">To Apply</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Clock size={28} color="var(--warning)" />
            {toApply.length}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Applications Sent</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <CheckCircle size={28} color="var(--primary)" />
            {applied.length}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Avg. Match Score</div>
          <div className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Star size={28} color="var(--warning)" fill="var(--warning)" />
            {avgScore}
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">Recent High Matches</h2>
        <div className="job-list">
          {goodMatches.slice(0, 3).map(job => (
            <div key={job.id} className="job-item">
              <div className="job-info">
                <h3>{job.title}</h3>
                <div className="job-meta">
                  <span>{job.company}</span>
                  <span>•</span>
                  <span>{job.location}</span>
                </div>
              </div>
              <div className="job-actions" style={{ alignItems: 'center' }}>
                <div className={`score-${job.score >= 8 ? 'high' : job.score >= 5 ? 'medium' : 'low'}`} style={{ fontWeight: 'bold', marginRight: '1rem' }}>
                  {job.score}/10 Match
                </div>
                <Link to={`/jobs/${job.id}`} className="btn btn-outline">View Details</Link>
              </div>
            </div>
          ))}
          {goodMatches.length === 0 && <p className="text-muted">No high match jobs found yet.</p>}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
