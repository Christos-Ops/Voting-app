const API_ROOT = '/api';

export async function api(path, options = {}) {
  const token = localStorage.getItem('ballot-token');
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || 'Something went wrong. Please try again.');
  return payload;
}

export function toIsoDate(value) {
  return value ? new Date(value).toISOString() : '';
}

export function formatDate(value) {
  if (!value) return 'Not set';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}