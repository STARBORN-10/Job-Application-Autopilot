import { createContext, useContext } from 'react';

export const ToastContext = createContext({ notify: () => {} });
export const PipelineContext = createContext(null);
export const AuthContext = createContext(null);

// notify({ type: 'success' | 'error' | 'info', title, message, timeout })
export const useToast = () => useContext(ToastContext);

// Live state of the job search run, shared by every page (see PipelineProvider).
export const usePipeline = () => useContext(PipelineContext);

// The signed-in account and sign-in functions (see AuthProvider). `user` is null when accounts are off on the server.
export const useAuth = () => useContext(AuthContext);
