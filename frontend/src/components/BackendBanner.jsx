import React, { useEffect, useState } from 'react';
import { pingBackend } from '../api';
import { AlertCircle } from 'lucide-react';

// Shows a banner while the backend is unreachable (e.g. a free host that is still waking up),
// keeps retrying in the background, and disappears once the backend answers.
const BackendBanner = () => {
  const [down, setDown] = useState(false);
  const [attempts, setAttempts] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer;

    const check = async () => {
      try {
        await pingBackend();
        if (cancelled) return;
        // Recovered: reload once so pages that failed while the backend was asleep load their data.
        setDown(prev => {
          if (prev) window.location.reload();
          return false;
        });
      } catch {
        if (cancelled) return;
        setDown(true);
        setAttempts(n => n + 1);
        timer = setTimeout(check, 6000);
      }
    };

    check();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  if (!down) return null;

  return (
    <div style={{
      background: 'rgba(245, 158, 11, 0.12)', color: 'var(--warning)',
      border: '1px solid rgba(245, 158, 11, 0.35)', borderRadius: 'var(--radius-md)',
      padding: '0.75rem 1.25rem', marginBottom: '1.25rem',
      display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.9rem',
    }}>
      <AlertCircle size={18} />
      <span>
        The server is not responding yet. Free hosting can take a minute or two to wake up
        {attempts > 1 ? ` (retrying… attempt ${attempts})` : ''}. This page will reload automatically when it is ready.
      </span>
    </div>
  );
};

export default BackendBanner;
