import { Directory, File, Paths } from 'expo-file-system';
import { getApiBaseUrl } from './config';
import { getAccessToken } from '../storage/authTokens';
import { ApiClientError, parseApiDetail } from '../utils/errors';
import { friendlyVoiceError } from '../utils/voiceErrors';
import type { TranscribeResponse } from '../types/voice';
import { STT_REQUEST_TIMEOUT_MS, TTS_REQUEST_TIMEOUT_MS } from '../constants/voice';

export async function transcribeAudio(
  fileUri: string,
  mimeType: string,
  languageHint?: string
): Promise<TranscribeResponse> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiClientError('Not signed in.', 401);
  }

  const form = new FormData();
  form.append('audio', {
    uri: fileUri,
    name: mimeType.includes('wav') ? 'recording.wav' : 'recording.webm',
    type: mimeType,
  } as unknown as Blob);

  if (languageHint) {
    form.append('language_hint', languageHint);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), STT_REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${getApiBaseUrl()}/chat/voice/transcribe`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: form,
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
          : friendlyVoiceError(null, response.status);
      throw new ApiClientError(detail, response.status);
    }

    if (typeof data !== 'object' || data === null) {
      throw new ApiClientError('Could not understand your voice. Please try again or type your question.');
    }

    return data as TranscribeResponse;
  } catch (err) {
    if (err instanceof ApiClientError) throw err;
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiClientError('Voice transcription took too long. Please try again.');
    }
    throw new ApiClientError(friendlyVoiceError(err));
  } finally {
    clearTimeout(timer);
  }
}

export async function synthesizeSpeech(
  text: string,
  responseLanguage: string,
  requestId?: string
): Promise<{ uri: string; mimeType: string }> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiClientError('Not signed in.', 401);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TTS_REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${getApiBaseUrl()}/chat/voice/synthesize`, {
      method: 'POST',
      headers: {
        Accept: 'audio/mpeg',
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        text,
        response_language: responseLanguage,
        request_id: requestId || null,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = friendlyVoiceError(null, response.status);
      try {
        const errJson = await response.json();
        if (errJson?.detail) detail = parseApiDetail(errJson.detail);
      } catch {
        // non-json error body
      }
      throw new ApiClientError(detail, response.status);
    }

    const mimeType = response.headers.get('content-type') || 'audio/mpeg';
    const buffer = await response.arrayBuffer();
    const file = new File(Paths.cache, `gramsakhi-tts-${Date.now()}.mp3`);
    const stream = file.writableStream();
    const writer = stream.getWriter();
    await writer.write(new Uint8Array(buffer));
    await writer.close();
    return { uri: file.uri, mimeType };
  } catch (err) {
    if (err instanceof ApiClientError) throw err;
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiClientError('Speech playback took too long to prepare. Please try again.');
    }
    throw new ApiClientError(friendlyVoiceError(err));
  } finally {
    clearTimeout(timer);
  }
}

export async function deleteTempAudio(uri: string | null | undefined): Promise<void> {
  if (!uri) return;
  try {
    const file = new File(uri);
    if (file.exists) {
      file.delete();
    }
  } catch {
    // best-effort cleanup
  }
}

/**
 * Remove TTS audio files left in the cache by a previous session that was
 * killed mid-playback. Best effort; runs once at startup.
 */
export function sweepStaleVoiceCache(): void {
  try {
    const cacheDir = new Directory(Paths.cache);
    for (const entry of cacheDir.list()) {
      if (entry instanceof File && entry.name.startsWith('gramsakhi-tts-')) {
        try {
          entry.delete();
        } catch {
          // best-effort cleanup
        }
      }
    }
  } catch {
    // best-effort cleanup
  }
}
