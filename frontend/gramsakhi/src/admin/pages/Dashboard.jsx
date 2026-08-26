import React, { useState, useEffect } from "react";
import { BookOpen, CheckCircle2, Loader2, AlertTriangle, Layers, ArrowRight, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import api from "../services/api";

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchMetrics = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get("/dashboard/summary");
      setMetrics(res.data);
    } catch (err) {
      setError("Failed to load dashboard metrics. Please reload.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
  }, []);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <p className="text-destructive text-sm font-semibold">{error}</p>
        <button
          onClick={fetchMetrics}
          className="mt-4 flex items-center gap-2 px-4 py-2 bg-secondary text-foreground text-sm font-semibold rounded-lg border border-border hover:bg-secondary/80 transition-all duration-200"
        >
          <RefreshCw className="w-4 h-4" />
          Retry
        </button>
      </div>
    );
  }

  const statCards = [
    {
      title: "Knowledge Documents",
      value: metrics?.total_documents || 0,
      description: "Government scheme documents in the corpus",
      icon: BookOpen,
      link: "/admin/knowledge",
      color: "from-teal-500/10 to-emerald-500/10 text-teal-400 border-teal-500/20",
    },
    {
      title: "Indexed",
      value: metrics?.indexed_documents || 0,
      description: "Ready for retrieval",
      icon: CheckCircle2,
      link: "/admin/knowledge",
      color: "from-blue-500/10 to-indigo-500/10 text-blue-400 border-blue-500/20",
    },
    {
      title: "Processing",
      value: metrics?.processing_documents || 0,
      description: "Upload / indexing in progress",
      icon: Layers,
      link: "/admin/knowledge",
      color: "from-amber-500/10 to-orange-500/10 text-amber-400 border-amber-500/20",
    },
    {
      title: "Failed",
      value: metrics?.failed_documents || 0,
      description: "Need re-upload or review",
      icon: AlertTriangle,
      link: "/admin/knowledge",
      color: "from-rose-500/10 to-red-500/10 text-rose-400 border-rose-500/20",
    },
  ];

  return (
    <div className="p-8 space-y-8 fade-in">
      <div className="p-6 rounded-2xl glass border border-border relative overflow-hidden flex flex-col md:flex-row items-center justify-between gap-6">
        <div className="space-y-1.5 text-center md:text-left">
          <h3 className="text-xl font-bold text-white font-display">Welcome to GramSakhi Admin</h3>
          <p className="text-sm text-muted-foreground">
            Manage verified government scheme documents for the knowledge base.
          </p>
        </div>
        <button
          onClick={fetchMetrics}
          className="flex items-center gap-2 px-4 py-2.5 bg-secondary hover:bg-secondary/80 text-foreground text-xs font-bold rounded-lg border border-border transition-all duration-200"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh Stats
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {statCards.map((card) => (
          <Link
            key={card.title}
            to={card.link}
            className={`p-5 rounded-2xl border bg-gradient-to-br ${card.color} hover:scale-[1.01] transition-transform`}
          >
            <div className="flex items-start justify-between mb-4">
              <card.icon className="w-5 h-5" />
              <ArrowRight className="w-4 h-4 opacity-60" />
            </div>
            <p className="text-3xl font-bold text-white mb-1">{card.value}</p>
            <p className="text-sm font-semibold text-white/90">{card.title}</p>
            <p className="text-xs text-muted-foreground mt-1">{card.description}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
