import React, { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, BookOpen, Layers, Calendar, User, Loader2 } from "lucide-react";
import api from "../services/api";

export default function DocumentDetail() {
  const { documentId } = useParams();
  const [doc, setDoc] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchDocDetail = async () => {
      setLoading(true);
      setError("");
      try {
        const dRes = await api.get(`/knowledge-base/${documentId}`);
        setDoc(dRes.data);
        const cRes = await api.get(`/knowledge-base/${documentId}/chunks`);
        setChunks(cRes.data);
      } catch (err) {
        setError("Failed to fetch document details.");
      } finally {
        setLoading(false);
      }
    };
    fetchDocDetail();
  }, [documentId]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error || !doc) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <p className="text-destructive text-sm font-semibold">{error || "Not found"}</p>
        <Link
          to="/admin/knowledge"
          className="mt-4 flex items-center gap-2 px-4 py-2 bg-secondary text-foreground text-sm font-semibold rounded-lg border border-border"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to list
        </Link>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-8 fade-in flex-1">
      <Link
        to="/admin/knowledge"
        className="inline-flex items-center gap-2 text-xs font-bold text-muted-foreground hover:text-white uppercase"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Knowledge Base
      </Link>

      <div className="p-6 rounded-2xl bg-card border border-border flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400 shrink-0">
            <BookOpen className="w-6 h-6" />
          </div>
          <div className="space-y-1">
            <h3 className="text-xl font-bold text-white font-display leading-tight">{doc.title}</h3>
            <p className="text-sm text-muted-foreground">
              {doc.scheme_name || "Government scheme"} · {doc.category} · {doc.indexing_status}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5" />
            {doc.chunk_count} chunks
          </span>
          <span className="inline-flex items-center gap-1.5">
            <User className="w-3.5 h-3.5" />
            {doc.uploader_name || "Admin"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Calendar className="w-3.5 h-3.5" />
            {new Date(doc.created_at).toLocaleDateString()}
          </span>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
        {[
          ["Ministry", doc.ministry],
          ["State", doc.state],
          ["Source", doc.source],
          ["Language", doc.language],
        ].map(([label, value]) => (
          <div key={label} className="p-3 rounded-xl border border-border bg-card/50">
            <p className="text-[10px] uppercase font-bold text-muted-foreground">{label}</p>
            <p className="text-white mt-1">{value || "—"}</p>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        <h4 className="text-sm font-bold text-white uppercase tracking-wide">Indexed chunks</h4>
        {chunks.length === 0 ? (
          <p className="text-sm text-muted-foreground">No chunks available.</p>
        ) : (
          chunks.map((c) => (
            <div key={c.id} className="p-4 rounded-xl border border-border bg-card space-y-2">
              <div className="flex justify-between text-[10px] uppercase font-bold text-muted-foreground">
                <span>Chunk #{c.chunk_index}</span>
                <span>Page {c.metadata?.page ?? "—"}</span>
              </div>
              <p className="text-sm text-foreground/90 whitespace-pre-wrap">{c.content}</p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
