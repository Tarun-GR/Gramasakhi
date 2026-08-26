import { getApiBaseUrl } from './config';
import { getAccessToken } from '../storage/authTokens';
import { ApiClientError, parseApiDetail } from '../utils/errors';
import type { ApiRequestOptions } from './types';

const DEFAULT_TIMEOUT_MS = 15000;

/**
 * Typed fetch wrapper for the existing GramSakhi FastAPI backend.
 * Does not log tokens or phone numbers.
 */
export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const {
    method = 'GET',
    body,
    token,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    skipAuth = false,
  } = options;

  const url = `${getApiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`;
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  if (!skipAuth && token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    const text = await response.text();
    let data: unknown = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }

    if (!response.ok) {
      const detail =
        typeof data === 'object' && data !== null && 'detail' in data
          ? parseApiDetail((data as { detail: unknown }).detail)
          : `Request failed (${response.status}).`;
      throw new ApiClientError(detail, response.status);
    }

    return data as T;
  } catch (err) {
    if (err instanceof ApiClientError) throw err;
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiClientError('The request took too long. Please try again.');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Attach stored JWT for authenticated backend calls (Phase 3+). */
export async function authenticatedRequest<T>(
  path: string,
  options: Omit<ApiRequestOptions, 'token' | 'skipAuth'> = {}
): Promise<T> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiClientError('Not signed in.', 401);
  }
  return apiRequest<T>(path, { ...options, token });
}

/** Health check — uses root /health (not /api prefix). */
export async function fetchHealth(): Promise<{ status: string; service: string }> {
  const { getApiOrigin } = await import('./config');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`${getApiOrigin()}/health`, {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new ApiClientError('GramSakhi service is unavailable.', response.status);
    }
    return (await response.json()) as { status: string; service: string };
  } finally {
    clearTimeout(timer);
  }
}
