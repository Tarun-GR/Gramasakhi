import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Globe2,
  Loader2,
  RefreshCw,
  Shield,
} from "lucide-react";
import api from "../services/api";

export default function GovRegistry() {
  const [sources, setSources] = useState([]);
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [reg, h] = await Promise.all([
        api.get("/gov-registry"),
        api.get("/gov-registry/health"),
      ]);
      setSources(reg.data?.sources || []);
      setStats(reg.data?.stats || null);
      setHealth(h.data || null);
    } catch {
      setError("Failed to load government registry.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const refreshIgod = async () => {
    setBusyId("refresh");
    try {
      await api.post("/gov-registry/refresh");
      await load();
    } catch {
      /* toast via interceptor */
    } finally {
      setBusyId(null);
    }
  };

  const toggleEnabled = async (sourceId, enabled) => {
    setBusyId(sourceId);
    try {
      await api.patch(`/gov-registry/${encodeURIComponent(sourceId)}`, { enabled: !enabled });
      await load();
    } catch {
      /* toast via interceptor */
    } finally {
      setBusyId(null);
    }
  };

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
          type="button"
          onClick={load}
          className="mt-4 flex items-center gap-2 px-4 py-2 bg-secondary text-foreground text-sm font-semibold rounded-lg border border-border"
        >
          <RefreshCw className="w-4 h-4" />
          Retry
        </button>
      </div>
    );
  }

  const acquisition = health?.acquisition || {};
  const browserOk = !!acquisition.browser_runtime_available;

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-6xl mx-auto w-full">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Shield className="w-5 h-5 text-primary" />
            Trusted government sources
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Only registered hosts are trusted. Links from myScheme do not inherit trust.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={load}
            className="flex items-center gap-2 px-3 py-2 text-sm font-semibold rounded-lg border border-border bg-secondary hover:bg-secondary/80"
          >
            <RefreshCw className="w-4 h-4" />
            Reload
          </button>
          <button
            type="button"
            onClick={refreshIgod}
            disabled={busyId === "refresh"}
            className="flex items-center gap-2 px-3 py-2 text-sm font-semibold rounded-lg bg-primary text-primary-foreground disabled:opacity-50"
          >
            {busyId === "refresh" ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Globe2 className="w-4 h-4" />
            )}
            Refresh from IGOD
          </button>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground font-medium">Enabled sources</p>
          <p className="text-2xl font-bold mt-1">{sources.filter((s) => s.enabled).length}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground font-medium">Registry total</p>
          <p className="text-2xl font-bold mt-1">{stats?.total ?? stats?.sources ?? sources.length}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground font-medium">Browser acquisition</p>
          <p className="text-sm font-semibold mt-2 flex items-center gap-2">
            {browserOk ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-amber-400" />
            )}
            {browserOk ? "Playwright ready" : "Chromium unavailable"}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground font-medium">Live attempts</p>
          <p className="text-2xl font-bold mt-1">{acquisition.attempts ?? 0}</p>
          <p className="text-[11px] text-muted-foreground mt-1">
            ok {acquisition.successes ?? 0} · fail {acquisition.failures ?? 0}
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-secondary/60 text-muted-foreground text-xs uppercase tracking-wide">
              <tr>
                <th className="text-left px-4 py-3 font-semibold">Source</th>
                <th className="text-left px-4 py-3 font-semibold">Domain</th>
                <th className="text-left px-4 py-3 font-semibold">Level</th>
                <th className="text-left px-4 py-3 font-semibold">Health</th>
                <th className="text-right px-4 py-3 font-semibold">Enabled</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.id} className="border-t border-border/80 hover:bg-secondary/30">
                  <td className="px-4 py-3 font-medium text-foreground">{s.name || s.id}</td>
                  <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{s.domain}</td>
                  <td className="px-4 py-3 text-muted-foreground">{s.level || "—"}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs font-semibold px-2 py-1 rounded-md bg-secondary">
                      {s.health || (s.enabled ? "active" : "disabled")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      disabled={busyId === s.id}
                      onClick={() => toggleEnabled(s.id, !!s.enabled)}
                      className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition ${
                        s.enabled
                          ? "border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10"
                          : "border-border text-muted-foreground hover:bg-secondary"
                      }`}
                    >
                      {busyId === s.id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin inline" />
                      ) : s.enabled ? (
                        "On"
                      ) : (
                        "Off"
                      )}
                    </button>
                  </td>
                </tr>
              ))}
              {!sources.length && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    No sources in registry.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
