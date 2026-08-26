import { ApiClientError } from './errors';

export function friendlyVoiceError(err: unknown, status?: number): string {
  if (err instanceof ApiClientError) {
    if (err.status === 401) return 'Please sign in again to continue.';
    if (err.status === 413) return 'Recording is too large. Please record a shorter message.';
    if (err.status === 429) return 'Too many voice requests. Please wait a moment and try again.';
    if (err.status === 503) return 'Voice service is temporarily unavailable. Please try again.';
    if (err.message) return err.message;
  }
  if (status === 401) return 'Please sign in again to continue.';
  if (status === 413) return 'Recording is too large. Please record a shorter message.';
  if (status === 429) return 'Too many voice requests. Please wait a moment and try again.';
  if (status === 503) return 'Voice service is temporarily unavailable. Please try again.';
  if (status && status >= 500) return 'Voice service hit an error. Please try again.';
  if (err instanceof Error) {
    if (err.name === 'AbortError' || err.message.includes('took too long')) {
      return 'The voice request took too long. Please try again.';
    }
    if (err.message.includes('Network request failed') || err.message.includes('Failed to fetch')) {
      return 'Cannot reach GramSakhi right now. Check your connection and try again.';
    }
  }
  return 'Could not complete the voice request. Please try again or type your question.';
}

export function mapTranscribeFailure(data: {
  success?: boolean;
  message?: string | null;
  error?: string | null;
}): string {
  if (data.message) return data.message;
  if (data.error === 'empty_audio') return 'No speech was detected. Please try again.';
  if (data.error === 'audio_too_large') return 'Recording is too large. Please record a shorter message.';
  if (data.error === 'audio_too_long') return 'Recording is too long. Please keep it under one minute.';
  if (data.error === 'unsupported_audio_format') {
    return 'This recording format is not supported. Please try again.';
  }
  return 'Could not understand your voice. Please try again or type your question.';
}

export function isAuthError(err: unknown): boolean {
  return err instanceof ApiClientError && err.status === 401;
}
