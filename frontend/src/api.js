const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export const fetchJobs = async () => {
  const response = await fetch(`${API_URL}/jobs`);
  if (!response.ok) throw new Error('Failed to fetch jobs');
  return response.json();
};

export const fetchJob = async (id) => {
  const response = await fetch(`${API_URL}/jobs/${id}`);
  if (!response.ok) throw new Error('Failed to fetch job');
  return response.json();
};

export const updateJob = async (id, data) => {
  const response = await fetch(`${API_URL}/jobs/${id}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Failed to update job');
  return response.json();
};

export const deleteJob = async (id) => {
  const response = await fetch(`${API_URL}/jobs/${id}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error('Failed to delete job');
  return response.json();
};
