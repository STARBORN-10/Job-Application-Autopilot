import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import BackendBanner from './components/BackendBanner';
import ToastProvider from './context/ToastProvider';
import PipelineProvider from './context/PipelineProvider';
import Dashboard from './pages/Dashboard';
import JobListings from './pages/JobListings';
import JobDetails from './pages/JobDetails';
import Tracker from './pages/Tracker';
import Analytics from './pages/Analytics';
import Settings from './pages/Settings';
import ResumeManager from './pages/ResumeManager';
import Applications from './pages/Applications';
import './index.css';

const NotFound = () => (
  <div className="card empty-state">
    <p><strong>Page not found.</strong></p>
    <p><Link to="/">Back to the dashboard</Link></p>
  </div>
);

function App() {
  return (
    <Router>
      <ToastProvider>
        <PipelineProvider>
          <div className="app-container">
            <Sidebar />
            <main className="main-content">
              <BackendBanner />
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/jobs" element={<JobListings />} />
                <Route path="/jobs/:id" element={<JobDetails />} />
                <Route path="/tracker" element={<Tracker />} />
                <Route path="/applications" element={<Applications />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/resumes" element={<ResumeManager />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </main>
          </div>
        </PipelineProvider>
      </ToastProvider>
    </Router>
  );
}

export default App;
