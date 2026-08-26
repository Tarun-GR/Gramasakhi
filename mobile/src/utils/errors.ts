/**
 * Map API/network failures to citizen-friendly messages (no stack traces).
 */
export function friendlyErrorMessage(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (err instanceof ApiClientError) {
    return err.message;
  }
  if (err instanceof Error) {
    if (err.message.includes('Network request failed') || err.message.includes('Failed to fetch')) {
      return 'Cannot reach GramSakhi right now. Check your connection and try again.';
    }
    if (err.message.includes('timeout') || err.message.includes('Timeout')) {
      return 'The request took too long. Please try again.';
    }
  }
  return fallback;
}

export class ApiClientError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
  }
}

const GENERIC_DETAIL = 'Request failed. Please try again.';

// Markers that indicate an internal/technical message that must never reach a citizen.
const INTERNAL_DETAIL_PATTERN =
  /traceback|stack trace|sqlalchemy|psycopg|sqlite|exception|\.py\b|file "|internal server|nonetype|keyerror|valueerror|attributeerror/i;

const MAX_DETAIL_LENGTH = 200;

function sanitizeDetailText(text: string): string {
  const trimmed = text.trim();
  if (!trimmed || trimmed.length > MAX_DETAIL_LENGTH || INTERNAL_DETAIL_PATTERN.test(trimmed)) {
    return GENERIC_DETAIL;
  }
  return trimmed;
}

export function parseApiDetail(detail: unknown): string {
  if (typeof detail === 'string') return sanitizeDetailText(detail);
  if (Array.isArray(detail)) {
    const joined = detail
      .map((item) => (typeof item === 'object' && item && 'msg' in item ? String(item.msg) : String(item)))
      .join(' ');
    return sanitizeDetailText(joined);
  }
  return GENERIC_DETAIL;
}
