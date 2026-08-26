/** Voice API types matching backend/app/schemas/voice.py */

export interface TranscribeResponse {
  success: boolean;
  text?: string | null;
  original_transcript?: string | null;
  normalized_transcript?: string | null;
  detected_language?: string | null;
  confidence?: number | null;
  low_confidence?: boolean;
  request_id?: string | null;
  latency_ms?: number | null;
  stt_model?: string | null;
  error?: string | null;
  message?: string | null;
}

export interface SynthesizeRequest {
  text: string;
  response_language: string;
  request_id?: string | null;
}

export type VoicePermissionState = 'unknown' | 'granted' | 'denied' | 'blocked';

export type VoiceInputPhase =
  | 'idle'
  | 'requesting_permission'
  | 'recording'
  | 'stopping'
  | 'uploading'
  | 'transcribing'
  | 'transcribed'
  | 'error';

export type TtsPlaybackPhase = 'idle' | 'loading' | 'playing' | 'error';

export interface VoiceSendOptions {
  input_mode: 'voice';
  stt_language: string;
  voice_request_id?: string;
}
