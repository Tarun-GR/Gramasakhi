'use client';

import { useState, useCallback, useEffect } from 'react';
import { useLanguageStore } from '@/stores/language-store';

export function useSpeechSynth() {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const { isTtsEnabled, getCurrentLanguageObj } = useLanguageStore();

  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  const speak = useCallback((text) => {
    if (!isTtsEnabled || typeof window === 'undefined' || !window.speechSynthesis) {
      return;
    }

    window.speechSynthesis.cancel();

    // Strip markdown formatting for cleaner speech output
    const cleanText = text
      .replace(/[#*_`~[\]()]/g, '')
      .replace(/- /g, '')
      .trim();

    if (!cleanText) return;

    const utterance = new SpeechSynthesisUtterance(cleanText);
    const langObj = getCurrentLanguageObj();
    utterance.lang = langObj?.speechCode || 'kn-IN';
    utterance.rate = 0.95; // Friendly cadence

    utterance.onstart = () => setIsSpeaking(true);
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);

    window.speechSynthesis.speak(utterance);
  }, [isTtsEnabled, getCurrentLanguageObj]);

  const stop = useCallback(() => {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      setIsSpeaking(false);
    }
  }, []);

  return {
    isSpeaking,
    speak,
    stop,
  };
}
