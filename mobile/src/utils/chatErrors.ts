import { ApiClientError } from '../utils/errors';

/** Citizen-friendly chat error messages (no stack traces). */
export function friendlyChatError(err: unknown): string {
  if (err instanceof ApiClientError) {
    if (err.status === 401) return 'Please sign in again to continue.';
    if (err.status === 429) return 'Too many requests. Please wait a moment and try again.';
    if (err.status === 503) return 'GramSakhi is temporarily unavailable. Please try again.';
    if (err.status && err.status >= 500) {
      return 'The server hit an error while answering. Please try once more.';
    }
    if (err.message) return err.message;
  }
  if (err instanceof Error) {
    if (err.name === 'AbortError' || err.message.includes('took too long')) {
      return 'The request took too long. Please try again.';
    }
    if (err.message.includes('Network request failed') || err.message.includes('Failed to fetch')) {
      return 'GramSakhi could not complete your request. Please check your connection and try again.';
    }
  }
  return 'GramSakhi could not complete your request. Please check your connection and try again.';
}

export function isAuthError(err: unknown): boolean {
  return err instanceof ApiClientError && err.status === 401;
}
