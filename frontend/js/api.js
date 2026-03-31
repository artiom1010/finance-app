const BASE = window.API_BASE_URL ?? '/api';

async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = Array.isArray(err.detail)
      ? err.detail.map(e => e.msg ?? JSON.stringify(e)).join(', ')
      : (typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
    throw new Error(detail ?? 'Request failed');
  }
  return res.json();
}

export const api = {
  auth:        (initData)                   => request('POST', '/auth', { initData }),
  getStats:    (userId, period, yearMonth)  => {
    const ym = yearMonth ? `&year_month=${yearMonth}` : '';
    return request('GET', `/stats?user_id=${userId}&period=${period ?? 'month'}${ym}`);
  },
  getTransactions: (userId, limit=20, offset=0, yearMonth) => {
    const ym = yearMonth ? `&year_month=${yearMonth}` : '';
    return request('GET', `/transactions?user_id=${userId}&limit=${limit}&offset=${offset}${ym}`);
  },
  addTransaction:  (data)                   => request('POST', '/transactions', data),
  deleteTransaction: (id, userId)           => request('DELETE', `/transactions/${id}?user_id=${userId}`),
  getCategories: (userId, type)             =>
    request('GET', `/categories?user_id=${userId}${type ? `&type=${type}` : ''}`),
  getHiddenCategories: (userId)             => request('GET', `/categories/hidden?user_id=${userId}`),
  addCategory:   (data)                     => request('POST', '/categories', data),
  deleteCategory:(id, userId)               => request('DELETE', `/categories/${id}?user_id=${userId}`),
  hideCategory:  (id, userId)               => request('POST', `/categories/${id}/hide?user_id=${userId}`),
  unhideCategory:(id, userId)               => request('POST', `/categories/${id}/unhide?user_id=${userId}`),
  getLimits:     (userId)                   => request('GET', `/limits?user_id=${userId}`),
  setLimit:      (data)                     => request('POST', '/limits', data),
  deleteLimit:   (categoryId, userId)       => request('DELETE', `/limits/${categoryId}?user_id=${userId}`),
  getRecurring:  (userId)                   => request('GET', `/recurring?user_id=${userId}`),
  addRecurring:  (data)                     => request('POST', '/recurring', data),
  deleteRecurring:(id, userId)              => request('DELETE', `/recurring/${id}?user_id=${userId}`),
};
