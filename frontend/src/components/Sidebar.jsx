import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Briefcase, ListTodo, Settings, Send } from 'lucide-react';

const Sidebar = () => {
  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <Send size={24} color="var(--primary)" />
        <span>Autopilot</span>
      </div>
      
      <div className="sidebar-nav">
        <NavLink 
          to="/" 
          className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
        >
          <LayoutDashboard size={20} />
          <span>Dashboard</span>
        </NavLink>
        
        <NavLink 
          to="/jobs" 
          className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
        >
          <Briefcase size={20} />
          <span>Job Listings</span>
        </NavLink>

        <NavLink 
          to="/tracker" 
          className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
        >
          <ListTodo size={20} />
          <span>Tracker</span>
        </NavLink>
        
        <NavLink 
          to="/settings" 
          className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
        >
          <Settings size={20} />
          <span>Settings</span>
        </NavLink>
      </div>
    </div>
  );
};

export default Sidebar;
