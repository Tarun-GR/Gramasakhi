import React, { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  Search,
  Upload,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Loader2,
  FileText,
} from "lucide-react";
import api, { apiEvents } from "../services/api";
import ConfirmDialog from "../components/ConfirmDialog";

const CATEGORIES = [
  { value: "GOVERNMENT_SCHEMES", label: "Government Schemes" },
  { value: "ELIGIBILITY", label: "Eligibility Guidelines" },
  { value: "APPLICATION", label: "Application Procedures" },
  { value: "BENEFITS", label: "Benefits & Entitlements" },
  { value: "OTHER", label: "Other" },
];

const emptyUpload = {
  title: "",
  category: "GOVERNMENT_SCHEMES",
  version: "1.0",
  scheme_name: "",
  ministry: "",
  state: "",
  source: "",
  language: "en",
  document_type: "PDF",
  file: null,
};

export default function KnowledgeBase() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [uploadForm, setUploadForm] = useState(emptyUpload);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [actionDocId, setActionDocId] = useState(null);

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get("/knowledge-base", {
        params: {
          page,
          limit: 10,
          search: search || undefined,
          category: categoryFilter,
        },
      });
      setDocuments(res.data.items);
      setTotal(res.data.total);
      setTotalPages(res.data.total_pages);
    } catch (err) {
      setError("Failed to retrieve knowledge base documents.");
    } finally {
      setLoading(false);
    }
  }, [page, search, categoryFilter]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setPage(1);
    fetchDocuments();
  };

  const handleUploadSubmit = async (e) => {
    e.preventDefault();
    if (!uploadForm.file) {
      setUploadError("Please select a document file to upload.");
      return;
    }

    setUploadLoading(true);
    setUploadError("");

    const formData = new FormData();
    formData.append("title", uploadForm.title);
    formData.append("category", uploadForm.category);
    formData.append("version", uploadForm.version);
    formData.append("file", uploadForm.file);
    if (uploadForm.scheme_name) formData.append("scheme_name", uploadForm.scheme_name);
    if (uploadForm.ministry) formData.append("ministry", uploadForm.ministry);
    if (uploadForm.state) formData.append("state", uploadForm.state);
    if (uploadForm.source) formData.append("source", uploadForm.source);
    if (uploadForm.language) formData.append("language", uploadForm.language);
    if (uploadForm.document_type) formData.append("document_type", uploadForm.document_type);

    try {
      await api.post("/knowledge-base/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 180000,
      });
      setIsUploadOpen(false);
      setUploadForm(emptyUpload);
      apiEvents.emit("toast", {
        type: "success",
        message: "Document uploaded and indexed successfully.",
      });
      fetchDocuments();
    } catch (err) {
      setUploadError(err.response?.data?.detail || "Ingestion pipeline failure. Check server logs.");
    } finally {
      setUploadLoading(false);
    }
  };

  const executeDelete = async () => {
    try {
      await api.delete(`/knowledge-base/${actionDocId}`);
      apiEvents.emit("toast", { type: "success", message: "Document deleted successfully." });
      fetchDocuments();
    } catch (err) {
      // global toast
    }
  };

  return (
    <div className="p-8 space-y-8 fade-in flex-1">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <h3 className="text-xl font-bold text-white font-display">Government Knowledge Base</h3>
          <p className="text-sm text-muted-foreground">
            Upload and index verified government scheme documents for GramSakhi retrieval.
          </p>
        </div>
        <button
          onClick={() => setIsUploadOpen(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-semibold rounded-lg shadow-lg shadow-primary/10 transition-all"
        >
          <Upload className="w-4 h-4" />
          Upload Document
        </button>
      </div>

      <div className="flex flex-col gap-4 p-4 rounded-xl bg-card border border-border">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <form onSubmit={handleSearchSubmit} className="relative w-full lg:max-w-xs">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search document title..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-input border border-border rounded-lg text-sm text-white placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </form>
          <select
            value={categoryFilter}
            onChange={(e) => {
              setCategoryFilter(e.target.value);
              setPage(1);
            }}
            className="px-3 py-2 bg-input border border-border rounded-lg text-xs text-white focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="all">All Categories</option>
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-20">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
        </div>
      ) : error ? (
        <p className="text-destructive text-sm font-semibold">{error}</p>
      ) : documents.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-border rounded-2xl text-muted-foreground">
          No documents yet. Upload a government scheme PDF to begin.
        </div>
      ) : (
        <div className="space-y-3">
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="p-4 rounded-xl bg-card border border-border flex flex-col sm:flex-row sm:items-center justify-between gap-4"
            >
              <div className="flex items-start gap-3 min-w-0">
                <div className="w-10 h-10 rounded-lg bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400 shrink-0">
                  <FileText className="w-5 h-5" />
                </div>
                <div className="min-w-0">
                  <Link
                    to={`/admin/knowledge/${doc.id}`}
                    className="font-semibold text-white hover:text-primary truncate block"
                  >
                    {doc.title}
                  </Link>
                  <p className="text-xs text-muted-foreground mt-1">
                    {doc.scheme_name || "Scheme"} · {doc.category} · {doc.indexing_status} ·{" "}
                    {doc.chunk_count} chunks
                  </p>
                </div>
              </div>
              <button
                onClick={() => {
                  setActionDocId(doc.id);
                  setConfirmDeleteOpen(true);
                }}
                className="inline-flex items-center gap-2 px-3 py-2 text-xs font-semibold text-destructive hover:bg-destructive/10 rounded-lg"
              >
                <Trash2 className="w-4 h-4" />
                Delete
              </button>
            </div>
          ))}

          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4">
              <p className="text-xs text-muted-foreground">
                Page {page} of {totalPages} · {total} documents
              </p>
              <div className="flex gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="px-3 py-2 rounded-lg border border-border disabled:opacity-40"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="px-3 py-2 rounded-lg border border-border disabled:opacity-40"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {isUploadOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
          <form
            onSubmit={handleUploadSubmit}
            className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-card border border-border p-6 space-y-4"
          >
            <h4 className="text-lg font-bold text-white">Upload government document</h4>
            {uploadError && (
              <p className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg p-3">
                {uploadError}
              </p>
            )}
            {[
              ["title", "Document title", true],
              ["scheme_name", "Scheme name", false],
              ["ministry", "Ministry", false],
              ["state", "State", false],
              ["source", "Source", false],
            ].map(([key, label, required]) => (
              <div key={key} className="space-y-1">
                <label className="text-xs font-bold text-muted-foreground uppercase">{label}</label>
                <input
                  required={required}
                  value={uploadForm[key]}
                  onChange={(e) => setUploadForm({ ...uploadForm, [key]: e.target.value })}
                  className="w-full px-3 py-2 bg-input border border-border rounded-lg text-sm text-white"
                />
              </div>
            ))}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-bold text-muted-foreground uppercase">Category</label>
                <select
                  value={uploadForm.category}
                  onChange={(e) => setUploadForm({ ...uploadForm, category: e.target.value })}
                  className="w-full px-3 py-2 bg-input border border-border rounded-lg text-sm text-white"
                >
                  {CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-bold text-muted-foreground uppercase">Language</label>
                <select
                  value={uploadForm.language}
                  onChange={(e) => setUploadForm({ ...uploadForm, language: e.target.value })}
                  className="w-full px-3 py-2 bg-input border border-border rounded-lg text-sm text-white"
                >
                  <option value="en">English</option>
                  <option value="hi">Hindi</option>
                  <option value="kn">Kannada</option>
                </select>
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-bold text-muted-foreground uppercase">File (PDF/TXT)</label>
              <input
                type="file"
                accept=".pdf,.txt"
                required
                onChange={(e) => setUploadForm({ ...uploadForm, file: e.target.files?.[0] || null })}
                className="w-full text-sm text-muted-foreground"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setIsUploadOpen(false)}
                className="px-4 py-2 rounded-lg border border-border text-sm"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={uploadLoading}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"
              >
                {uploadLoading ? "Processing..." : "Upload & Index"}
              </button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        isOpen={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={executeDelete}
        title="Delete document?"
        message="This removes the document and its indexed chunks from the knowledge base."
      />
    </div>
  );
}
