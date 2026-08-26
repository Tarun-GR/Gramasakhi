'use client';

import { useState, useRef, useCallback } from 'react';
import { useLanguageStore } from '@/stores/language-store';
import { transcribeVoice } from '@/lib/api/chat-api';
import { uiLangToApi } from '@/lib/api/backend-adapter';

/**
 * Voice input via GramSakhi backend STT (MediaRecorder + /chat/voice/transcribe).
 * Falls back to browser SpeechRecognition only when backend path is unavailable.
 */
export function useVoice() {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [error, setError] = useState(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const recognitionRef = useRef(null);
  const { getCurrentLanguageObj } = useLanguageStore();

  const stopTracks = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }, []);

  const startBackendRecording = useCallback(async (onResultCallback) => {
    setError(null);
    setTranscript('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stopTracks();
        setIsListening(false);
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        if (!blob.size) return;
        try {
          const langObj = getCurrentLanguageObj();
          const data = await transcribeVoice(blob, { language: langObj?.code });
          const text = (data.text || data.transcript || '').trim();
          if (text) {
            setTranscript(text);
            onResultCallback?.(text, {
              input_mode: 'voice',
              stt_language: uiLangToApi(langObj?.code),
              voice_request_id: data.voice_request_id || data.request_id,
            });
          }
        } catch (e) {
          setError('Could not understand your voice. Please try again or type your question.');
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsListening(true);
    } catch {
      setError('Microphone access was denied.');
      setIsListening(false);
    }
  }, [getCurrentLanguageObj, stopTracks]);

  const stopBackendRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop();
    } else {
      stopTracks();
      setIsListening(false);
    }
  }, [stopTracks]);

  const startBrowserRecognition = useCallback((onResultCallback) => {
    const SpeechRecognition = typeof window !== 'undefined'
      ? window.SpeechRecognition || window.webkitSpeechRecognition
      : null;
    if (!SpeechRecognition) {
      setError('Voice input is not supported in this browser.');
      return;
    }
    const langObj = getCurrentLanguageObj();
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = langObj?.speechCode || 'en-IN';
    recognition.onresult = (event) => {
      let text = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        text += event.results[i][0].transcript;
      }
      setTranscript(text);
      if (event.results[0]?.isFinal && text.trim()) {
        onResultCallback?.(text.trim(), { input_mode: 'voice', stt_language: uiLangToApi(langObj?.code) });
      }
    };
    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  }, [getCurrentLanguageObj]);

  const stopListening = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      stopBackendRecording();
      return;
    }
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        // ignore
      }
    }
    stopTracks();
    setIsListening(false);
  }, [stopBackendRecording, stopTracks]);

  const toggleListening = useCallback((onResultCallback) => {
    if (isListening) {
      stopListening();
    } else if (navigator.mediaDevices?.getUserMedia) {
      startBackendRecording(onResultCallback);
    } else {
      startBrowserRecognition(onResultCallback);
    }
  }, [isListening, startBackendRecording, startBrowserRecognition, stopListening]);

  return {
    isListening,
    transcript,
    error,
    stopListening,
    toggleListening,
  };
}
