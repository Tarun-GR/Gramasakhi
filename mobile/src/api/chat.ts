import { authenticatedRequest } from './client';
import { mapBackendChatResponse, mapConversationSummary, mapHistoryMessages, uiLangToApi } from './chatAdapter';
import type {
  BackendChatResponse,
  BackendConversationCreateResponse,
  BackendConversationHistoryResponse,
  BackendConversationListResponse,
  MappedChatResponse,
  SendMessagePayload,
} from '../types/chat';
import type { ConversationSummary, ChatMessage } from '../types/chat';

const CONV_PAGE = 30;
export const CHAT_REQUEST_TIMEOUT_MS = 270_000;

export async function listConversations(limit = CONV_PAGE, offset = 0): Promise<ConversationSummary[]> {
  const data = await authenticatedRequest<BackendConversationListResponse>(
    `/chat/conversations?limit=${limit}&offset=${offset}`
  );
  return (data.conversations || []).map(mapConversationSummary);
}

export async function loadConversationHistory(conversationId: string): Promise<{
  messages: ChatMessage[];
  conversationId: string;
  title?: string;
  language?: string;
}> {
  const data = await authenticatedRequest<BackendConversationHistoryResponse>(
    `/chat/conversations/${conversationId}`
  );
  return {
    conversationId: String(data.conversation_id || conversationId),
    title: data.title,
    language: data.language,
    messages: mapHistoryMessages(data.messages),
  };
}

export async function createEmptyConversation(body?: {
  title?: string;
  language?: string;
}): Promise<{ id: string; title?: string; language?: string }> {
  const data = await authenticatedRequest<BackendConversationCreateResponse>('/chat/conversations', {
    method: 'POST',
    body: body || {},
  });
  return { id: String(data.id), title: data.title, language: data.language };
}

export async function sendChatMessage(payload: SendMessagePayload): Promise<MappedChatResponse> {
  const data = await authenticatedRequest<BackendChatResponse>('/chat', {
    method: 'POST',
    timeoutMs: CHAT_REQUEST_TIMEOUT_MS,
    body: {
      message: payload.message,
      conversation_id: payload.conversation_id || null,
      language: uiLangToApi(payload.language),
      input_mode: payload.input_mode || 'text',
      stt_language: payload.stt_language || null,
      voice_request_id: payload.voice_request_id || null,
    },
  });
  return mapBackendChatResponse(data);
}
