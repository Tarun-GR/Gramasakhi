import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import api from "../services/api";
import { Landmark, LogOut, Mic, Send, Sun, Moon, Loader2 } from "lucide-react";

// 0 = no axios timeout — wait until the backend finishes (live gov can be slow)
const CHAT_TIMEOUT_MS = 0;

function friendlyChatError(err) {
  const code = err?.code;
  const status = err?.response?.status;
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (code === "ECONNABORTED" || /timeout/i.test(err?.message || "")) {
    return "The connection was interrupted while fetching government documents. Please try the same question again — do not refresh while it is loading.";
  }
  if (code === "ERR_NETWORK" || /network error/i.test(err?.message || "")) {
    return "Could not reach the GramSakhi server. Confirm the API is running on http://127.0.0.1:8000, then try again.";
  }
  if (status === 401) {
    return "Your session expired. Please log in again.";
  }
  if (status >= 500) {
    return "The server hit an error while answering. Please try once more.";
  }
  return "Could not get an answer. Please try again.";
}

export default function AskGramSakhi() {
  const { logout, phoneNumber, theme, toggleTheme, showToast } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [sending, setSending] = useState(false);
  const [waitHint, setWaitHint] = useState("");
  const [conversationId, setConversationId] = useState(
    () => localStorage.getItem("gramsakhiConversationId") || null
  );
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Namaste. I am GramSakhi. Ask me about government schemes — follow-up questions work in the same conversation.",
    },
  ]);

  useEffect(() => {
    if (!sending) {
      setWaitHint("");
      return undefined;
    }
    setWaitHint("Searching your verified knowledge base…");
    const t1 = setTimeout(
      () => setWaitHint("Checking official government websites when needed…"),
      12000
    );
    const t2 = setTimeout(
      () =>
        setWaitHint(
          "Still working on official government sources — please keep this tab open…"
        ),
      45000
    );
    const t3 = setTimeout(
      () =>
        setWaitHint(
          "Almost there — GramSakhi will show the answer as soon as verification finishes…"
        ),
      120000
    );
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [sending]);

  const handleLogout = () => {
    logout();
    localStorage.removeItem("gramsakhiConversationId");
    navigate("/login");
  };

  const startNewConversation = () => {
    localStorage.removeItem("gramsakhiConversationId");
    setConversationId(null);
    setMessages([
      {
        role: "assistant",
        content: "New conversation started. What scheme would you like to know about?",
      },
    ]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const text = query.trim();
    if (!text || sending) return;

    // Always show the original user text — never the rewritten retrieval query
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setQuery("");
    setSending(true);

    try {
      const res = await api.post(
        "/chat",
        {
          message: text,
          conversation_id: conversationId || null,
        },
        { timeout: CHAT_TIMEOUT_MS, skipErrorToast: true }
      );
      const data = res.data || {};
      if (data.conversation_id) {
        setConversationId(data.conversation_id);
        localStorage.setItem("gramsakhiConversationId", data.conversation_id);
      }
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer || "I don't have enough reliable information to answer that.",
          sources: data.sources || [],
          llm_invoked: data.llm_invoked,
          knowledge_source: data.knowledge_source,
        },
      ]);
    } catch (err) {
      const detail = friendlyChatError(err);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: detail,
        },
      ]);
      if (showToast) showToast("error", detail);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-50">
      <header className="px-6 py-4 flex items-center justify-between border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur sticky top-0 z-20">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 bg-emerald-700 text-white rounded-xl flex items-center justify-center">
            <Landmark className="h-5 w-5" />
          </div>
          <div>
            <span className="font-extrabold text-base tracking-tight text-emerald-800 dark:text-emerald-300">
              GramSakhi
            </span>
            <span className="text-[10px] block font-bold text-slate-400 -mt-0.5 tracking-wider uppercase">
              Ask · Citizen
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {phoneNumber && (
            <span className="hidden sm:inline text-xs text-slate-500">{phoneNumber}</span>
          )}
          <button
            type="button"
            onClick={startNewConversation}
            className="hidden sm:inline py-2 px-3 text-xs font-semibold rounded-xl bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
          >
            New chat
          </button>
          <button
            onClick={toggleTheme}
            className="p-2 rounded-xl bg-slate-100 dark:bg-slate-800"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 py-2 px-3 text-xs font-semibold rounded-xl bg-slate-100 dark:bg-slate-800"
          >
            <LogOut className="h-4 w-4" />
            Logout
          </button>
        </div>
      </header>

      <main className="flex-1 flex flex-col max-w-3xl w-full mx-auto px-4 py-6 gap-4">
        <div className="text-center space-y-2 py-6">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-emerald-900 dark:text-emerald-200">
            GramSakhi
          </h1>
          <p className="text-slate-600 dark:text-slate-400 text-sm sm:text-base">
            How can I help you with government schemes today?
          </p>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto min-h-[40vh]">
          {messages.map((m, idx) => (
            <div key={idx} className="space-y-1">
              <div
                className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                  m.role === "user"
                    ? "ml-auto bg-emerald-700 text-white"
                    : "mr-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-100"
                }`}
              >
                {m.content}
              </div>
              {m.role === "assistant" && m.sources?.length > 0 && (
                <div className="mr-auto max-w-[90%] text-[11px] text-slate-500 px-1">
                  Sources:{" "}
                  {[
                    ...new Set(
                      m.sources
                        .map((s) => s.scheme_name || s.document_title || s.source)
                        .filter(Boolean)
                    ),
                  ].join(" · ")}
                  {m.knowledge_source === "live_government" ? " · live government" : ""}
                </div>
              )}
            </div>
          ))}
          {sending && (
            <div className="mr-auto flex items-center gap-2 text-sm text-slate-500 px-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              {waitHint || "Looking up verified government documents…"}
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit} className="sticky bottom-4 space-y-2">
          <div className="flex gap-2 items-end">
            <button
              type="button"
              className="p-3 rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-500"
              title="Voice input will be connected in Phase 7"
            >
              <Mic className="h-5 w-5" />
            </button>
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              rows={2}
              placeholder="Type your question about a scheme..."
              disabled={sending}
              className="flex-1 resize-none rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-600 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={sending || !query.trim()}
              className="p-3 rounded-2xl bg-emerald-700 text-white hover:bg-emerald-800 disabled:opacity-50"
              aria-label="Send"
            >
              {sending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
            </button>
          </div>
          <p className="text-[11px] text-center text-slate-400">
            Answers are grounded in verified government documents. Please keep this tab open until the answer appears.
          </p>
        </form>
      </main>
    </div>
  );
}
