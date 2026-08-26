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
import {
  createEmptyConversation,
  listConversations,
  loadConversationHistory,
  sendChatMessage,
} from '../api/chat';
import { useAuth } from '../context/AuthContext';
import {
  clearConversationId,
  getConversationId,
  setConversationId,
} from '../storage/authTokens';
import type { ChatMessage, ConversationSummary } from '../types/chat';
import type { VoiceSendOptions } from '../types/voice';
import { DEFAULT_UI_LANGUAGE, type UiLanguageCode } from '../constants/language';
import { normalizeUiLanguage } from '../utils/language';
import { friendlyChatError, isAuthError } from '../utils/chatErrors';

interface ChatContextValue {
  conversations: ConversationSummary[];
  loadingConversations: boolean;
  activeConversationId: string | null;
  messages: ChatMessage[];
  loadingMessages: boolean;
  isGenerating: boolean;
  error: string | null;
  initialized: boolean;
  fetchConversations: () => Promise<ConversationSummary[]>;
  bootstrapChat: () => Promise<void>;
  loadConversation: (id: string) => Promise<void>;
  selectConversation: (id: string) => void;
  newConsultation: () => Promise<void>;
  sendMessage: (text: string, language?: UiLanguageCode | string, voiceOpts?: VoiceSendOptions) => Promise<void>;
  getChatGeneration: () => number;
  handleAuthFailure: () => Promise<void>;
  clearError: () => void;
  resetSession: () => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const { status, expireSession } = useAuth();

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(false);

  const chatGenerationRef = useRef(0);
  const loadRequestSeqRef = useRef(0);
  const sendRequestSeqRef = useRef(0);
  const sendInFlightRef = useRef(false);
  const newConsultationInFlightRef = useRef(false);
  const forceNewRef = useRef(false);
  const bootstrapStartedRef = useRef(false);

  const handleAuthFailure = useCallback(async () => {
    chatGenerationRef.current += 1;
    loadRequestSeqRef.current += 1;
    sendRequestSeqRef.current += 1;
    sendInFlightRef.current = false;
    newConsultationInFlightRef.current = false;
    forceNewRef.current = false;
    setConversations([]);
    setActiveConversationId(null);
    setMessages([]);
    setLoadingMessages(false);
    setIsGenerating(false);
    setError(null);
    setInitialized(false);
    bootstrapStartedRef.current = false;
    await clearConversationId();
    await expireSession();
  }, [expireSession]);

  const resetSession = useCallback(() => {
    chatGenerationRef.current += 1;
    loadRequestSeqRef.current += 1;
    sendRequestSeqRef.current += 1;
    sendInFlightRef.current = false;
    newConsultationInFlightRef.current = false;
    forceNewRef.current = false;
    bootstrapStartedRef.current = false;
    setConversations([]);
    setActiveConversationId(null);
    setMessages([]);
    setLoadingConversations(false);
    setLoadingMessages(false);
    setIsGenerating(false);
    setError(null);
    setInitialized(false);
    void clearConversationId();
  }, []);

  useEffect(() => {
    if (status === 'unauthenticated') {
      resetSession();
    }
  }, [status, resetSession]);

  const fetchConversations = useCallback(async () => {
    setLoadingConversations(true);
    try {
      const rows = await listConversations();
      setConversations(rows);
      return rows;
    } catch (err) {
      if (isAuthError(err)) {
        await handleAuthFailure();
        return [];
      }
      setConversations([]);
      return [];
    } finally {
      setLoadingConversations(false);
    }
  }, [handleAuthFailure]);

  const loadConversation = useCallback(
    async (id: string) => {
      if (!id) return;
      const seq = loadRequestSeqRef.current + 1;
      loadRequestSeqRef.current = seq;
      setLoadingMessages(true);
      setError(null);
      setActiveConversationId(id);
      setMessages([]);

      try {
        const data = await loadConversationHistory(id);
        if (seq !== loadRequestSeqRef.current) return;
        setMessages(data.messages);
        setActiveConversationId(data.conversationId);
        setLoadingMessages(false);
        setInitialized(true);
        forceNewRef.current = false;
        await setConversationId(data.conversationId);
      } catch (err) {
        if (seq !== loadRequestSeqRef.current) return;
        if (isAuthError(err)) {
          await handleAuthFailure();
          return;
        }
        setMessages([]);
        setLoadingMessages(false);
        setInitialized(true);
        setError("We couldn't load this conversation. Please try again.");
      }
    },
    [handleAuthFailure]
  );

  const createAndActivateConversation = useCallback(async () => {
    const gen = chatGenerationRef.current;
    try {
      const created = await createEmptyConversation();
      if (gen !== chatGenerationRef.current) return null;
      forceNewRef.current = false;
      await setConversationId(created.id);
      setActiveConversationId(created.id);
      setMessages([]);
      setError(null);
      setInitialized(true);
      await fetchConversations();
      return created.id;
    } catch (err) {
      if (isAuthError(err)) {
        await handleAuthFailure();
        return null;
      }
      setError(friendlyChatError(err));
      return null;
    }
  }, [fetchConversations, handleAuthFailure]);

  const bootstrapChat = useCallback(async () => {
    if (bootstrapStartedRef.current || status !== 'authenticated') return;
    bootstrapStartedRef.current = true;
    setInitialized(false);
    setError(null);

    const rows = await fetchConversations();

    if (forceNewRef.current) {
      setActiveConversationId(null);
      setMessages([]);
      setInitialized(true);
      return;
    }

    const storedId = await getConversationId();
    if (storedId) {
      const seq = loadRequestSeqRef.current + 1;
      loadRequestSeqRef.current = seq;
      setLoadingMessages(true);
      setActiveConversationId(storedId);
      setMessages([]);
      try {
        const data = await loadConversationHistory(storedId);
        if (seq !== loadRequestSeqRef.current) return;
        setMessages(data.messages);
        setActiveConversationId(data.conversationId);
        setLoadingMessages(false);
        forceNewRef.current = false;
        await setConversationId(data.conversationId);
        setInitialized(true);
        return;
      } catch (err) {
        if (seq !== loadRequestSeqRef.current) return;
        if (isAuthError(err)) {
          await handleAuthFailure();
          return;
        }
        setLoadingMessages(false);
        await clearConversationId();
      }
    }

    if (rows.length > 0) {
      await loadConversation(rows[0].id);
      setInitialized(true);
      return;
    }

    await createAndActivateConversation();
    setInitialized(true);
  }, [status, fetchConversations, loadConversation, createAndActivateConversation, handleAuthFailure]);

  const selectConversation = useCallback(
    (id: string) => {
      if (!id) return;
      if (String(id) === String(activeConversationId)) return;
      chatGenerationRef.current += 1;
      sendRequestSeqRef.current += 1;
      sendInFlightRef.current = false;
      forceNewRef.current = false;
      setIsGenerating(false);
      setError(null);
      void loadConversation(id);
    },
    [activeConversationId, loadConversation]
  );

  const newConsultation = useCallback(async () => {
    if (newConsultationInFlightRef.current) return;
    newConsultationInFlightRef.current = true;
    chatGenerationRef.current += 1;
    sendRequestSeqRef.current += 1;
    sendInFlightRef.current = false;
    forceNewRef.current = true;
    setIsGenerating(false);
    setError(null);
    setMessages([]);
    setActiveConversationId(null);
    try {
      await clearConversationId();
      await createAndActivateConversation();
    } finally {
      newConsultationInFlightRef.current = false;
    }
  }, [createAndActivateConversation]);

  const sendMessage = useCallback(
    async (text: string, language?: UiLanguageCode | string, voiceOpts?: VoiceSendOptions) => {
      const trimmed = text.trim();
      if (!trimmed || sendInFlightRef.current) return;

      const requestLanguage = normalizeUiLanguage(language, DEFAULT_UI_LANGUAGE) ?? DEFAULT_UI_LANGUAGE;

      sendInFlightRef.current = true;
      const gen = chatGenerationRef.current;
      const sendSeq = sendRequestSeqRef.current + 1;
      sendRequestSeqRef.current = sendSeq;
      const outboundConversationId = activeConversationId;

      setIsGenerating(true);
      setError(null);

      const userMsg: ChatMessage = {
        id: `msg-usr-${Date.now()}`,
        role: 'user',
        content: trimmed,
        timestamp: new Date().toISOString(),
        input_mode: voiceOpts?.input_mode || 'text',
      };
      setMessages((prev) => [...prev, userMsg]);

      const assistantTempId = `msg-ast-${Date.now()}`;

      try {
        const data = await sendChatMessage({
          message: trimmed,
          conversation_id: outboundConversationId,
          language: requestLanguage,
          input_mode: voiceOpts?.input_mode || 'text',
          stt_language: voiceOpts?.stt_language || null,
          voice_request_id: voiceOpts?.voice_request_id || null,
        });

        if (
          gen !== chatGenerationRef.current ||
          sendSeq !== sendRequestSeqRef.current
        ) {
          setIsGenerating(false);
          if (sendSeq === sendRequestSeqRef.current) sendInFlightRef.current = false;
          return;
        }

        if (data.conversation_id) {
          forceNewRef.current = false;
          await setConversationId(data.conversation_id);
          if (String(activeConversationId) !== String(data.conversation_id)) {
            setActiveConversationId(data.conversation_id);
          }
        }

        const assistantMsg: ChatMessage = {
          id: assistantTempId,
          role: 'assistant',
          content: data.message,
          timestamp: new Date().toISOString(),
          sources: data.sources || [],
          schemes: data.schemes || [],
          grounding: data.grounding,
          meta: data.meta,
          language: data.language,
        };

        setMessages((prev) => [...prev, assistantMsg]);
        setIsGenerating(false);
        sendInFlightRef.current = false;
        void fetchConversations();
      } catch (err) {
        if (
          gen !== chatGenerationRef.current ||
          sendSeq !== sendRequestSeqRef.current
        ) {
          setIsGenerating(false);
          if (sendSeq === sendRequestSeqRef.current) sendInFlightRef.current = false;
          return;
        }
        if (isAuthError(err)) {
          setIsGenerating(false);
          sendInFlightRef.current = false;
          await handleAuthFailure();
          return;
        }
        setIsGenerating(false);
        sendInFlightRef.current = false;
        setError(friendlyChatError(err));
      }
    },
    [activeConversationId, fetchConversations, handleAuthFailure]
  );

  const clearError = useCallback(() => setError(null), []);

  const getChatGeneration = useCallback(() => chatGenerationRef.current, []);

  const value = useMemo(
    () => ({
      conversations,
      loadingConversations,
      activeConversationId,
      messages,
      loadingMessages,
      isGenerating,
      error,
      initialized,
      fetchConversations,
      bootstrapChat,
      loadConversation,
      selectConversation,
      newConsultation,
      sendMessage,
      getChatGeneration,
      handleAuthFailure,
      clearError,
      resetSession,
    }),
    [
      conversations,
      loadingConversations,
      activeConversationId,
      messages,
      loadingMessages,
      isGenerating,
      error,
      initialized,
      fetchConversations,
      bootstrapChat,
      loadConversation,
      selectConversation,
      newConsultation,
      sendMessage,
      getChatGeneration,
      handleAuthFailure,
      clearError,
      resetSession,
    ]
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChat must be used within ChatProvider');
  return ctx;
}
