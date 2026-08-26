import type { RecordingOptions } from 'expo-audio';
import { AudioQuality, IOSOutputFormat } from 'expo-audio';

/** Android webm recording aligned with web client + backend STT (audio/webm). */
export const GRAMSAKHI_RECORDING_OPTIONS: RecordingOptions = {
  extension: '.webm',
  sampleRate: 16000,
  numberOfChannels: 1,
  bitRate: 64000,
  android: {
    extension: '.webm',
    outputFormat: 'webm',
    audioEncoder: 'aac',
    sampleRate: 16000,
  },
  ios: {
    extension: '.wav',
    outputFormat: IOSOutputFormat.LINEARPCM,
    audioQuality: AudioQuality.HIGH,
    linearPCMBitDepth: 16,
    linearPCMIsBigEndian: false,
    linearPCMIsFloat: false,
    sampleRate: 16000,
  },
  web: {
    mimeType: 'audio/webm',
    bitsPerSecond: 64000,
  },
};

/** Backend STT max upload (settings.STT_MAX_AUDIO_SIZE_MB). */
export const STT_MAX_BYTES = 8 * 1024 * 1024;

/** Match web chat-api STT timeout; backend STT_TIMEOUT_SECONDS ≈ 90. */
export const STT_REQUEST_TIMEOUT_MS = 120_000;

/** Match backend TTS_TIMEOUT_SECONDS. */
export const TTS_REQUEST_TIMEOUT_MS = 60_000;
