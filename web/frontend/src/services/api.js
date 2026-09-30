import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// Token CSRF (double-submit): el backend lo valida contra el guardado en la sesión
// (ver web/app.py CSRFProtect + web/routes/api.py::csrf_token). Se cachea en memoria y
// se re-pide solo cuando falta o cuando login/logout invalidan la sesión anterior
// (invalidateCsrfToken, llamado desde useAuthStore).
let csrfTokenPromise = null;
const MUTATING_METHODS = new Set(['post', 'put', 'patch', 'delete']);

function fetchCsrfToken() {
  if (!csrfTokenPromise) {
    csrfTokenPromise = api.get('/csrf-token')
      .then((data) => data.csrf_token)
      .catch((err) => {
        csrfTokenPromise = null;
        throw err;
      });
  }
  return csrfTokenPromise;
}

export function invalidateCsrfToken() {
  csrfTokenPromise = null;
}

api.interceptors.request.use(async (config) => {
  const method = (config.method || '').toLowerCase();
  if (MUTATING_METHODS.has(method) && config.url !== '/csrf-token') {
    config.headers['X-CSRFToken'] = await fetchCsrfToken();
  }
  return config;
});

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response && error.response.status === 401) {
      // Unauthenticated event
      window.dispatchEvent(new Event('unauthorized'));
    }
    return Promise.reject(error);
  }
);

export default api;
