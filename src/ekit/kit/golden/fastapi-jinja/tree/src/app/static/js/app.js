// Progressive enhancement only: every flow works without JavaScript.
// Adds the CSRF header to fetch() calls made by feature scripts.
const token = document.cookie.split("; ").find((c) => c.startsWith("csrftoken="))?.split("=")[1];
export function csrfFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token) headers.set("X-CSRF-Token", token);
  return fetch(url, { ...options, headers });
}
