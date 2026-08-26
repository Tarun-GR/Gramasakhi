import type {
  AssistanceMeta,
  BackendChatResponse,
  BackendConversationSummary,
  BackendHistoryMessage,
  ChatMessage,
  ChatSource,
  ConversationSummary,
  MappedChatResponse,
} from '../types/chat';
import { DEFAULT_UI_LANGUAGE } from '../constants/language';
import { isSupportedLanguage, normalizeUiLanguage } from '../utils/language';

const LANG_TO_API: Record<string, string> = { kn: 'KN', hi: 'HI', en: 'EN' };
const LANG_FROM_API: Record<string, string> = { KN: 'kn', HI: 'hi', EN: 'en' };

export function uiLangToApi(code?: string): string {
  const normalized = normalizeUiLanguage(code, DEFAULT_UI_LANGUAGE) ?? DEFAULT_UI_LANGUAGE;
  return LANG_TO_API[normalized];
}

/** Map backend language code to supported UI code, or null if unknown. */
export function apiLangToUi(code?: string | null): string | null {
  if (!code) return null;
  const upper = code.toUpperCase();
  if (LANG_FROM_API[upper]) return LANG_FROM_API[upper];
  const lower = code.toLowerCase();
  return isSupportedLanguage(lower) ? lower : null;
}

/** Map backend evidence_status to mobile grounding sufficiency (no reinterpretation). */
export function mapEvidenceSufficiency(status?: string | null): 'SUPPORTED' | 'PARTIAL' | 'UNSUPPORTED' {
  const s = (status || '').toUpperCase();
  if (s === 'SUPPORTED') return 'SUPPORTED';
  if (s === 'UNSUPPORTED') return 'UNSUPPORTED';
  return 'PARTIAL';
}

export function normalizeSources(
  sources: Record<string, unknown>[] = [],
  officialSources: Record<string, unknown>[] = []
): ChatSource[] {
  const seen = new Set<string>();
  const out: ChatSource[] = [];
  for (const s of [...sources, ...officialSources]) {
    const url = String(s?.document_url || s?.url || s?.source || '');
    if (!url || !/^https?:\/\//i.test(url) || seen.has(url)) continue;
    seen.add(url);
    const isPdf = Boolean(s?.is_pdf) || /\.pdf(\?|$)/i.test(url);
    out.push({
      id: url,
      url,
      title: String(
        s?.scheme_name ||
          s?.document_title ||
          s?.name ||
          (isPdf ? 'Official scheme document (PDF)' : 'Official source')
      ),
      department: s?.department ? String(s.department) : undefined,
      is_pdf: isPdf,
    });
  }
  return out;
}

export function buildAssistantMeta(data: BackendChatResponse | null | undefined): AssistanceMeta | null {
  if (!data) return null;
  const meta: AssistanceMeta = {
    citizen_intent: data.citizen_intent,
    assistance_mode: data.assistance_mode,
    detected_scheme: data.detected_scheme,
    eligibility_status: data.eligibility_status,
    eligibility_evaluation: data.eligibility_evaluation,
    eligibility_explanation: data.eligibility_explanation,
    scheme_guidance: data.scheme_guidance ?? null,
    eligibility_session_active: data.eligibility_session_active,
    eligibility_question: data.eligibility_question,
    eligibility_completed: data.eligibility_completed,
    known_information: data.known_information,
    missing_information: data.missing_information,
    required_information: data.required_information,
    action_plan: data.action_plan ?? null,
  };
  const has = Object.values(meta).some(
    (v) => v != null && v !== '' && !(Array.isArray(v) && v.length === 0)
  );
  return has ? meta : null;
}

export function mapBackendChatResponse(data: BackendChatResponse | null | undefined): MappedChatResponse {
  if (!data || typeof data !== 'object') {
    return {
      message: "I don't have enough reliable information to answer that.",
      sources: [],
      schemes: [],
      grounding: { sufficiency: 'UNSUPPORTED' },
      meta: null,
    };
  }
  const answer = data.answer || "I don't have enough reliable information to answer that.";
  const validated = Boolean(data.validated);
  return {
    conversation_id: data.conversation_id,
    title: data.title,
    message: answer,
    language: apiLangToUi(data.response_language || data.detected_language) ?? undefined,
    sources: normalizeSources(data.sources, data.official_sources),
    schemes: data.detected_scheme
      ? [{ id: String(data.detected_scheme), name: data.detected_scheme }]
      : [],
    grounding: {
      sufficiency: validated
        ? 'SUPPORTED'
        : data.live_status === 'FAILED'
          ? 'UNSUPPORTED'
          : 'PARTIAL',
      confidenceScore: validated ? 0.95 : undefined,
      verificationNote: validated
        ? 'Verified against official government documents'
        : data.live_reason || data.reason || undefined,
    },
    meta: buildAssistantMeta(data),
  };
}

export function mapHistoryMessages(rows: BackendHistoryMessage[] | null | undefined): ChatMessage[] {
  const list = Array.isArray(rows) ? rows : [];
  return list.map((m) => {
    if (!m || typeof m !== 'object') {
      return {
        id: `msg-bad-${Date.now()}`,
        role: 'assistant',
        content: '',
        timestamp: null,
        sources: [],
        schemes: [],
      };
    }
    const isAssistant = m.role === 'assistant';
    const sufficiency = mapEvidenceSufficiency(m.evidence_status);
    const meta = m.assistance_meta ? { ...m.assistance_meta } : null;
    return {
      id: String(m.id),
      role: m.role,
      content: m.content || '',
      timestamp: m.created_at,
      input_mode: m.input_mode,
      sources: isAssistant ? normalizeSources(m.sources, m.official_sources) : [],
      schemes: meta?.detected_scheme
        ? [{ id: String(meta.detected_scheme), name: String(meta.detected_scheme) }]
        : [],
      grounding: isAssistant
        ? {
            sufficiency,
            verificationNote:
              sufficiency === 'SUPPORTED' ? 'Verified against official documents' : undefined,
          }
        : undefined,
      meta,
      language: apiLangToUi(m.language) ?? undefined,
    };
  });
}

export function mapConversationSummary(row: BackendConversationSummary): ConversationSummary {
  return {
    id: String(row.id),
    title: row.title || 'Conversation',
    createdAt: row.updated_at || row.last_message_at || row.created_at,
    language: row.language,
  };
}
