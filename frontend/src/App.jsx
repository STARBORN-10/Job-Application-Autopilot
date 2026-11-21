import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import BackendBanner from './components/BackendBanner';
import Dashboard from './pages/Dashboard';
import JobListings from './pages/JobListings';
import JobDetails from './pages/JobDetails';
import Tracker from './pages/Tracker';
import Analytics from './pages/Analytics';
import Settings from './pages/Settings';
import ResumeManager from './pages/ResumeManager';
import './index.css';

function App() {
  return (
    <Router>
      <div className="app-container">
        <Sidebar />
        <main className="main-content">
          <BackendBanner />
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/jobs" element={<JobListings />} />
            <Route path="/jobs/:id" element={<JobDetails />} />
            <Route path="/tracker" element={<Tracker />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/resumes" element={<ResumeManager />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
