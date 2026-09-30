import { create } from 'zustand';
import api, { invalidateCsrfToken } from '../services/api';

export const useAuthStore = create((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  checkAuth: async () => {
    try {
      set({ isLoading: true, error: null });
      const res = await api.get('/auth/me');
      if (res.authenticated) {
        set({ user: res.user, isAuthenticated: true, isLoading: false });
      } else {
        set({ user: null, isAuthenticated: false, isLoading: false });
      }
    } catch (err) {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  login: async (username, password) => {
    try {
      set({ isLoading: true, error: null });
      const res = await api.post('/auth/login', { username, password });
      if (res.success) {
        // login_user() hace session.clear() en el backend: el token CSRF de antes de
        // loguearse queda invalidado, hay que pedir uno nuevo para la sesión logueada.
        invalidateCsrfToken();
        set({ user: res.user, isAuthenticated: true, isLoading: false });
        return { success: true };
      } else {
        set({ error: res.error || 'Credenciales inválidas', isLoading: false });
        return { success: false, error: res.error };
      }
    } catch (err) {
      const msg = err.response?.data?.error || 'Error al iniciar sesión';
      set({ error: msg, isLoading: false });
      return { success: false, error: msg };
    }
  },

  logout: async () => {
    try {
      await api.post('/auth/logout');
    } catch (e) {
      // Ignore
    } finally {
      invalidateCsrfToken();
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  }
}));
