const rawBaseUrl = import.meta.env.VITE_API_URL || ''

function normalizeBaseUrl(url: string): string {
  if (!url) return ''
  let normalized = url.trim()
  // Remove trailing slashes and trailing dots (FQDN) that break URL construction
  while (normalized.endsWith('/') || normalized.endsWith('.')) {
    normalized = normalized.slice(0, -1)
  }
  return normalized
}

export const API_BASE_URL = normalizeBaseUrl(rawBaseUrl)

export function apiUrl(endpoint: string): string {
  const safeEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`
  return `${API_BASE_URL}${safeEndpoint}`
}

if (import.meta.env.DEV) {
  // eslint-disable-next-line no-console
  console.log('[DEV] VITE_API_URL raw:', rawBaseUrl, 'normalized:', API_BASE_URL)
}
