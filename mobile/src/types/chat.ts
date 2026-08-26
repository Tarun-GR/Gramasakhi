/** Mobile chat types aligned with existing GramSakhi backend (snake_case on wire). */

export interface ChatSource {
  id: string;
  url: string;
  title: string;
  department?: string;
  is_pdf?: boolean;
}

export interface ChatScheme {
  id: string;
  name: string;
}

export interface MessageGrounding {
  sufficiency?: 'SUPPORTED' | 'PARTIAL' | 'UNSUPPORTED';
  confidenceScore?: number;
  verificationNote?: string;
}

export interface AssistanceMeta {
  citizen_intent?: string | null;
  assistance_mode?: string | null;
  detected_scheme?: string | null;
  eligibility_status?: string | null;
  eligibility_evaluation?: unknown;
  eligibility_explanation?: unknown;
  scheme_guidance?: Record<string, unknown> | null;
  eligibility_session_active?: boolean | null;
  eligibility_question?: string | null;
  eligibility_completed?: boolean | null;
  known_information?: string[] | null;
  missing_information?: string[] | null;
  required_information?: string[] | null;
  action_plan?: Record<string, unknown> | null;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | string;
  content: string;
  timestamp?: string | null;
  input_mode?: string;
  sources?: ChatSource[];
  schemes?: ChatScheme[];
  grounding?: MessageGrounding;
  meta?: AssistanceMeta | null;
  language?: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  createdAt?: string | null;
  language?: string | null;
}

export interface MappedChatResponse {
  conversation_id?: string;
  title?: string;
  message: string;
  language?: string;
  sources: ChatSource[];
  schemes: ChatScheme[];
  grounding?: MessageGrounding;
  meta?: AssistanceMeta | null;
}

export interface SendMessagePayload {
  message: string;
  conversation_id?: string | null;
  language?: string;
  input_mode?: 'text' | 'voice';
  stt_language?: string | null;
  voice_request_id?: string | null;
}

/** Backend wire shapes (subset used by mobile). */
export interface BackendChatResponse {
  conversation_id?: string;
  title?: string;
  answer?: string;
  validated?: boolean;
  sources?: Record<string, unknown>[];
  official_sources?: Record<string, unknown>[];
  detected_language?: string;
  response_language?: string;
  live_status?: string;
  live_reason?: string;
  reason?: string;
  detected_scheme?: string;
  citizen_intent?: string;
  assistance_mode?: string;
  eligibility_status?: string;
  eligibility_evaluation?: unknown;
  eligibility_explanation?: unknown;
  scheme_guidance?: Record<string, unknown>;
  eligibility_session_active?: boolean;
  eligibility_question?: string;
  eligibility_completed?: boolean;
  known_information?: string[];
  missing_information?: string[];
  required_information?: string[];
  action_plan?: Record<string, unknown>;
}

export interface BackendConversationSummary {
  id: string;
  title?: string;
  language?: string;
  created_at?: string;
  updated_at?: string;
  last_message_at?: string;
}

export interface BackendConversationListResponse {
  conversations: BackendConversationSummary[];
  total: number;
  limit: number;
  offset: number;
  has_more?: boolean;
}

export interface BackendConversationHistoryResponse {
  conversation_id: string;
  title?: string;
  language?: string;
  messages: BackendHistoryMessage[];
  has_more?: boolean;
  assistance_state?: AssistanceMeta | null;
}

export interface BackendHistoryMessage {
  id: string;
  role: string;
  content: string;
  created_at?: string;
  input_mode?: string;
  language?: string;
  evidence_status?: string;
  sources?: Record<string, unknown>[];
  official_sources?: Record<string, unknown>[];
  assistance_meta?: AssistanceMeta | null;
}

export interface BackendConversationCreateResponse {
  id: string;
  title?: string;
  language?: string;
  created_at?: string;
}
