import React from 'react';

const Settings = () => {
  return (
    <div>
      <header className="page-header">
        <h1 className="page-title">Settings</h1>
        <p className="page-description">Configure your AI Job Application Autopilot preferences.</p>
      </header>

      <div className="card" style={{ maxWidth: '800px' }}>
        <h2 className="card-title">Job Search Preferences</h2>
        
        <div className="form-group">
          <label className="form-label">Target Roles</label>
          <input type="text" className="form-control" defaultValue="Frontend Developer, Full Stack Engineer, React Developer" />
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            Comma separated list of job titles you are looking for.
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">Preferred Locations</label>
          <input type="text" className="form-control" defaultValue="Remote, New York, San Francisco" />
        </div>

        <div style={{ display: 'flex', gap: '1.5rem' }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Minimum Match Score (1-10)</label>
            <input type="number" className="form-control" defaultValue="7" min="1" max="10" />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Only jobs above this score will be added to the dashboard.
            </div>
          </div>

          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Experience Level</label>
            <select className="form-control" defaultValue="mid">
              <option value="entry">Entry Level (0-2 years)</option>
              <option value="mid">Mid Level (3-5 years)</option>
              <option value="senior">Senior (5+ years)</option>
              <option value="lead">Lead / Staff</option>
            </select>
          </div>
        </div>
        
        <h2 className="card-title" style={{ marginTop: '2rem', borderTop: '1px solid var(--border)', paddingTop: '1.5rem' }}>External Integrations</h2>

        <div className="form-group">
          <label className="form-label">Make.com Webhook URL (Future)</label>
          <input type="password" className="form-control" placeholder="https://hook.make.com/..." disabled />
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            Used to trigger external automations (currently disabled).
          </div>
        </div>

        <button className="btn btn-primary" style={{ marginTop: '1rem' }} onClick={() => alert("Settings saved successfully!")}>
          Save Preferences
        </button>
      </div>
    </div>
  );
};

export default Settings;
