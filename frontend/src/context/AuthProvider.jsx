import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AuthContext, useToast } from './contexts';
import {
  SESSION_EXPIRED_EVENT, fetchAuthConfig, fetchMe, forgetToken, getToken, loginUser, registerUser, rememberToken,
} from '../api';
import { ErrorState, Spinner } from '../components/Feedback';
import AuthPage from '../pages/Auth';

const RETRY_SECONDS = 8;

// Decides what the visitor sees: a "connecting" screen, a retrying error, the sign-in page, or the app.
// Everything inside the app is mounted only for a signed-in user (or when the server has accounts turned off),
// so switching accounts never shows the previous person's data.
const AuthProvider = ({ children }) => {
  const { notify } = useToast();
  const [state, setState] = useState({ status: 'loading', config: null, user: null, error: null });
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async () => {
    try {
      const config = await fetchAuthConfig();
      if (!config.auth_enabled || !getToken()) {
        setState({ status: 'ready', config, user: null, error: null });
        return;
      }
      try {
        const me = await fetchMe();
        setState({ status: 'ready', config, user: me.user, error: null });
      } catch (err) {
        if (err.status !== 401) throw err;
        forgetToken();
        setState({ status: 'ready', config, user: null, error: null });
      }
    } catch (err) {
      setState({ status: 'error', config: null, user: null, error: err.message });
      setAttempt((n) => n + 1);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(load, 0);   // first check on mount (deferred: load() updates state)
    return () => clearTimeout(timer);
  }, [load]);

  // While the server is unreachable (e.g. a free host waking up) keep trying.
  useEffect(() => {
    if (state.status !== 'error') return undefined;
    const timer = setTimeout(load, RETRY_SECONDS * 1000);
    return () => clearTimeout(timer);
  }, [state.status, attempt, load]);

  // The server ended the session (expired, password changed elsewhere, account deleted).
  useEffect(() => {
    const onExpired = () => {
      setState((s) => (s.user ? { ...s, user: null } : s));
      notify({ type: 'info', title: 'Please sign in again', message: 'Your session ended.' });
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, [notify]);

  const startSession = useCallback((session) => {
    rememberToken(session.token);
    setState((s) => ({ ...s, user: session.user, config: s.config ? { ...s.config, first_account: false } : s.config }));
  }, []);

  const value = useMemo(() => ({
    config: state.config,
    user: state.user,
    accountsOn: Boolean(state.config?.auth_enabled),
    login: async (email, password) => startSession(await loginUser({ email, password })),
    register: async (data) => startSession(await registerUser(data)),
    logout: () => { forgetToken(); setState((s) => ({ ...s, user: null })); },
    setUser: (user) => setState((s) => ({ ...s, user })),
    adoptSession: startSession,   // after a password change the server returns a fresh token
  }), [state.config, state.user, startSession]);

  let body;
  if (state.status === 'loading') {
    body = (
      <div className="auth-page">
        <div className="auth-card card center-text">
          <Spinner size={30} label="Connecting" />
          <p className="muted" style={{ marginTop: '1rem' }}>Connecting to the server... a free host can take a minute to wake up.</p>
        </div>
      </div>
    );
  } else if (state.status === 'error') {
    body = (
      <div className="auth-page">
        <div className="auth-card card">
          <ErrorState title="The server is not responding yet" message={`${state.error} Trying again automatically every ${RETRY_SECONDS} seconds${attempt > 1 ? ` (attempt ${attempt})` : ''}.`}
            onRetry={load} />
        </div>
      </div>
    );
  } else if (value.accountsOn && !state.user) {
    body = <AuthPage />;
  } else {
    body = children;
  }
  return <AuthContext.Provider value={value}>{body}</AuthContext.Provider>;
};

export default AuthProvider;
