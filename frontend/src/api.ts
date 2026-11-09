export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = typeof error.detail === 'string' ? error.detail
      : Array.isArray(error.detail) ? error.detail.map((item: {msg?: string}) => item.msg ?? 'Invalid value').join('; ')
      : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export function jsonRequest(method: string, value: unknown): RequestInit {
  return {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(value)};
}
