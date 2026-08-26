import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getRecordingPermissionsAsync,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import { Linking, Platform } from 'react-native';
import { deleteTempAudio, transcribeAudio } from '../api/voice';
import { uiLangToApi } from '../api/chatAdapter';
import { DEFAULT_UI_LANGUAGE } from '../constants/language';
import { normalizeUiLanguage } from '../utils/language';
import { GRAMSAKHI_RECORDING_OPTIONS } from '../constants/voice';
import type { VoiceInputPhase, VoicePermissionState, VoiceSendOptions } from '../types/voice';
import { isAuthError, mapTranscribeFailure } from '../utils/voiceErrors';
import { ApiClientError } from '../utils/errors';

interface UseVoiceInputOptions {
  language?: string;
  disabled?: boolean;
  getChatGeneration: () => number;
  onAuthExpired: () => Promise<void>;
  onTranscribed: (text: string, options: VoiceSendOptions, requestLanguage: string) => Promise<void>;
  /**
   * Backend flagged the transcript as low confidence — hand the text to the
   * caller for review instead of auto-sending. Optional for backward compatibility.
   */
  onLowConfidence?: (text: string) => void;
}

function permissionFromStatus(status: string, canAskAgain?: boolean): VoicePermissionState {
  if (status === 'granted') return 'granted';
  if (status === 'denied' && canAskAgain === false) return 'blocked';
  if (status === 'denied') return 'denied';
  return 'unknown';
}

export function useVoiceInput({
  language = DEFAULT_UI_LANGUAGE,
  disabled,
  getChatGeneration,
  onAuthExpired,
  onTranscribed,
  onLowConfidence,
}: UseVoiceInputOptions) {
  const recorder = useAudioRecorder(GRAMSAKHI_RECORDING_OPTIONS);
  const recorderState = useAudioRecorderState(recorder);
  const [phase, setPhase] = useState<VoiceInputPhase>('idle');
  const [permission, setPermission] = useState<VoicePermissionState>('unknown');
  const [error, setError] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string | null>(null);

  const busyRef = useRef(false);
  const generationAtRecordRef = useRef(0);
  const languageAtRecordRef = useRef<typeof language>(language);
  const sttSeqRef = useRef(0);

  useEffect(() => {
    void (async () => {
      const current = await getRecordingPermissionsAsync();
      setPermission(permissionFromStatus(current.status, current.canAskAgain));
    })();
  }, []);

  const ensurePermission = useCallback(async (): Promise<boolean> => {
    setPhase('requesting_permission');
    const current = await getRecordingPermissionsAsync();
    let state = permissionFromStatus(current.status, current.canAskAgain);
    if (state === 'granted') {
      setPermission('granted');
      return true;
    }
    const requested = await requestRecordingPermissionsAsync();
    state = permissionFromStatus(requested.status, requested.canAskAgain);
    setPermission(state);
    if (state === 'granted') return true;
    if (state === 'blocked') {
      setError('Microphone access is blocked. Open settings to allow GramSakhi to use your microphone.');
    } else {
      setError('Microphone permission is required for voice input.');
    }
    setPhase('error');
    return false;
  }, []);

  const resetToIdle = useCallback(() => {
    setPhase('idle');
    busyRef.current = false;
  }, []);

  const startRecording = useCallback(async () => {
    if (disabled || busyRef.current || phase === 'recording') return;
    setError(null);
    setPreviewText(null);
    busyRef.current = true;

    const allowed = await ensurePermission();
    if (!allowed) {
      busyRef.current = false;
      return;
    }

    try {
      await setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true,
        shouldPlayInBackground: false,
      });
      await recorder.prepareToRecordAsync(GRAMSAKHI_RECORDING_OPTIONS);
      generationAtRecordRef.current = getChatGeneration();
      languageAtRecordRef.current = normalizeUiLanguage(language, DEFAULT_UI_LANGUAGE) ?? DEFAULT_UI_LANGUAGE;
      recorder.record();
      setPhase('recording');
    } catch {
      setError('Could not start recording. Please try again.');
      setPhase('error');
      busyRef.current = false;
    }
  }, [disabled, ensurePermission, getChatGeneration, phase, recorder]);

  const abortVoiceProcessing = useCallback(async () => {
    sttSeqRef.current += 1;
    setPreviewText(null);
    setError(null);
    try {
      if (recorder.isRecording) {
        await recorder.stop();
      }
    } catch {
      // ignore
    }
    const uri = recorder.uri;
    await deleteTempAudio(uri);
    resetToIdle();
  }, [recorder, resetToIdle]);

  const cancelRecording = useCallback(async () => {
    await abortVoiceProcessing();
  }, [abortVoiceProcessing]);

  const finishRecording = useCallback(async () => {
    if (!recorder.isRecording || busyRef.current === false) return;
    setPhase('stopping');
    const genAtRecord = generationAtRecordRef.current;
    const langAtRecord = languageAtRecordRef.current;
    const sttSeq = sttSeqRef.current + 1;
    sttSeqRef.current = sttSeq;

    let fileUri: string | null = null;
    let mimeType = Platform.OS === 'ios' ? 'audio/wav' : 'audio/webm';

    try {
      await recorder.stop();
      fileUri = recorder.uri || recorderState.url;
      setPhase('uploading');

      if (!fileUri) {
        throw new ApiClientError('No recording was captured. Please try again.');
      }

      setPhase('transcribing');
      const result = await transcribeAudio(fileUri, mimeType, uiLangToApi(langAtRecord));

      if (sttSeq !== sttSeqRef.current || genAtRecord !== getChatGeneration()) {
        resetToIdle();
        return;
      }

      if (!result.success) {
        throw new ApiClientError(mapTranscribeFailure(result));
      }

      const text = (result.text || '').trim();
      if (!text) {
        throw new ApiClientError('No speech was detected. Please try again.');
      }

      if (result.low_confidence === true && onLowConfidence) {
        // Safe UX policy: low-confidence transcripts are never auto-sent; the
        // citizen reviews/edits the text in the composer before sending.
        onLowConfidence(text);
        setPreviewText(null);
        resetToIdle();
        return;
      }

      setPreviewText(text);
      setPhase('transcribed');

      const voiceOpts: VoiceSendOptions = {
        input_mode: 'voice',
        stt_language: result.detected_language || uiLangToApi(langAtRecord),
        voice_request_id: result.request_id || undefined,
      };

      if (genAtRecord !== getChatGeneration()) {
        setPreviewText(null);
        resetToIdle();
        return;
      }

      await onTranscribed(text, voiceOpts, langAtRecord);
      setPreviewText(null);
      resetToIdle();
    } catch (err) {
      if (isAuthError(err)) {
        await onAuthExpired();
        resetToIdle();
        return;
      }
      setError(err instanceof ApiClientError ? err.message : 'Voice input failed. Please try again.');
      setPhase('error');
      busyRef.current = false;
    } finally {
      await deleteTempAudio(fileUri);
      try {
        await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
      } catch {
        // ignore
      }
    }
  }, [
    recorder,
    recorderState.url,
    language,
    getChatGeneration,
    onTranscribed,
    onLowConfidence,
    onAuthExpired,
    resetToIdle,
  ]);

  const openSettings = useCallback(() => {
    void Linking.openSettings();
  }, []);

  const clearError = useCallback(() => {
    setError(null);
    if (phase === 'error') setPhase('idle');
    busyRef.current = false;
  }, [phase]);

  useEffect(() => {
    return () => {
      sttSeqRef.current += 1;
      try {
        if (recorder.isRecording) {
          void recorder.stop();
        }
      } catch {
        // ignore
      }
      void deleteTempAudio(recorder.uri);
    };
  }, [recorder]);

  const isRecording = phase === 'recording';
  const isProcessing =
    phase === 'stopping' ||
    phase === 'uploading' ||
    phase === 'transcribing' ||
    phase === 'requesting_permission';

  return {
    phase,
    permission,
    error,
    previewText,
    isRecording,
    isProcessing,
    durationMillis: recorderState.durationMillis,
    startRecording,
    finishRecording,
    cancelRecording,
    abortVoiceProcessing,
    openSettings,
    clearError,
  };
}
