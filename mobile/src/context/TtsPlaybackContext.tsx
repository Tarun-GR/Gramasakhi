import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useAudioPlayer, useAudioPlayerStatus, setAudioModeAsync } from 'expo-audio';
import { deleteTempAudio, sweepStaleVoiceCache, synthesizeSpeech } from '../api/voice';
import { uiLangToApi } from '../api/chatAdapter';
import { DEFAULT_UI_LANGUAGE } from '../constants/language';
import type { TtsPlaybackPhase } from '../types/voice';
import { normalizeUiLanguage } from '../utils/language';
import { isAuthError } from '../utils/voiceErrors';
import { ApiClientError } from '../utils/errors';

interface TtsPlaybackContextValue {
  activeMessageId: string | null;
  phase: TtsPlaybackPhase;
  error: string | null;
  playMessage: (messageId: string, text: string, language?: string) => Promise<void>;
  stopPlayback: () => void;
  clearError: () => void;
}

const TtsPlaybackContext = createContext<TtsPlaybackContextValue | null>(null);

interface TtsPlaybackProviderProps {
  children: ReactNode;
  onAuthExpired?: () => Promise<void>;
}

function stripMarkdownForSpeech(text: string): string {
  return text
    .replace(/[#*_`~[\]()]/g, '')
    .replace(/- /g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function TtsPlaybackProvider({ children, onAuthExpired }: TtsPlaybackProviderProps) {
  const player = useAudioPlayer(null);
  const status = useAudioPlayerStatus(player);
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [phase, setPhase] = useState<TtsPlaybackPhase>('idle');
  const [error, setError] = useState<string | null>(null);
  const tempUriRef = useRef<string | null>(null);
  const playSeqRef = useRef(0);

  useEffect(() => {
    sweepStaleVoiceCache();
  }, []);

  const cleanupTemp = useCallback(async () => {
    await deleteTempAudio(tempUriRef.current);
    tempUriRef.current = null;
  }, []);

  const stopPlayback = useCallback(() => {
    playSeqRef.current += 1;
    try {
      player.pause();
      player.seekTo(0);
    } catch {
      // ignore
    }
    void cleanupTemp();
    setActiveMessageId(null);
    setPhase('idle');
  }, [player, cleanupTemp]);

  useEffect(() => {
    if (status.didJustFinish) {
      stopPlayback();
    }
  }, [status.didJustFinish, stopPlayback]);

  const playMessage = useCallback(
    async (messageId: string, text: string, language?: string) => {
      const cleaned = stripMarkdownForSpeech(text);
      if (!cleaned) return;

      const responseLanguage =
        normalizeUiLanguage(language, DEFAULT_UI_LANGUAGE) ?? DEFAULT_UI_LANGUAGE;

      if (activeMessageId === messageId && (phase === 'playing' || status.playing)) {
        stopPlayback();
        return;
      }

      stopPlayback();
      const seq = playSeqRef.current + 1;
      playSeqRef.current = seq;
      setPhase('loading');
      setError(null);
      setActiveMessageId(messageId);

      try {
        const { uri } = await synthesizeSpeech(cleaned, uiLangToApi(responseLanguage));
        if (seq !== playSeqRef.current) {
          await deleteTempAudio(uri);
          return;
        }
        tempUriRef.current = uri;
        await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
        player.replace(uri);
        player.play();
        setPhase('playing');
      } catch (err) {
        if (seq !== playSeqRef.current) return;
        if (isAuthError(err)) {
          stopPlayback();
          if (onAuthExpired) {
            await onAuthExpired();
          }
          return;
        }
        setPhase('error');
        setActiveMessageId(null);
        setError(
          err instanceof ApiClientError ? err.message : 'Could not play this response.'
        );
        await cleanupTemp();
      }
    },
    [activeMessageId, phase, status.playing, player, stopPlayback, cleanupTemp, onAuthExpired]
  );

  const clearError = useCallback(() => setError(null), []);

  useEffect(() => () => {
    stopPlayback();
  }, [stopPlayback]);

  const value = useMemo(
    () => ({
      activeMessageId,
      phase,
      error,
      playMessage,
      stopPlayback,
      clearError,
    }),
    [activeMessageId, phase, error, playMessage, stopPlayback, clearError]
  );

  return <TtsPlaybackContext.Provider value={value}>{children}</TtsPlaybackContext.Provider>;
}

export function useTtsPlayback(): TtsPlaybackContextValue {
  const ctx = useContext(TtsPlaybackContext);
  if (!ctx) throw new Error('useTtsPlayback must be used within TtsPlaybackProvider');
  return ctx;
}
