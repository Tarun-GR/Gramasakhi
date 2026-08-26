import React, { useState, useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";

import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import KnowledgeBase from "./pages/KnowledgeBase";
import DocumentDetail from "./pages/DocumentDetail";
import GovRegistry from "./pages/GovRegistry";
import { apiEvents } from "./services/api";

function AdminProtected({ children }) {
  const token = localStorage.getItem("superAdminToken");
  const role = localStorage.getItem("superAdminRole");
  if (!token || (role !== "SUPER_ADMIN" && role !== "ADMIN")) {
    localStorage.removeItem("superAdminToken");
    localStorage.removeItem("superAdminRole");
    localStorage.removeItem("superAdminEmail");
    localStorage.removeItem("superAdminName");
    return <Navigate to="/admin/login" replace />;
  }
  return children;
}

export default function AdminShell() {
  const location = useLocation();
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.documentElement.classList.add("dark");
    const unsubLoading = apiEvents.subscribe("loading", (state) => setLoading(state));
    const unsubToast = apiEvents.subscribe("toast", (t) => {
      setToast(t);
      setTimeout(() => setToast(null), 5000);
    });
    return () => {
      document.documentElement.classList.remove("dark");
      unsubLoading();
      unsubToast();
    };
  }, []);

  const getSectionTitle = () => {
    const path = location.pathname;
    if (path.startsWith("/admin/knowledge")) return "Government Knowledge Base";
    if (path.startsWith("/admin/registry")) return "Trusted Government Sources";
    if (path === "/admin" || path.startsWith("/admin/dashboard")) return "Dashboard Overview";
    return "GramSakhi Admin";
  };

  const isLoginPage = location.pathname === "/admin/login";

  if (isLoginPage) {
    return (
      <div className="min-h-screen bg-background flex text-foreground font-sans">
        {toast && (
          <div
            className={`fixed bottom-6 right-6 z-50 px-5 py-3.5 rounded-xl border shadow-2xl text-sm font-semibold max-w-sm ${
              toast.type === "error"
                ? "bg-destructive/15 border-destructive/20 text-destructive"
                : "bg-emerald-500/15 border-emerald-500/20 text-emerald-400"
            }`}
          >
            {toast.message}
          </div>
        )}
        <Login />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background flex text-foreground font-sans selection:bg-primary/30 selection:text-white">
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 px-5 py-3.5 rounded-xl border shadow-2xl flex items-center gap-3 text-sm font-semibold max-w-sm ${
            toast.type === "error"
              ? "bg-destructive/15 border-destructive/20 text-destructive"
              : "bg-emerald-500/15 border-emerald-500/20 text-emerald-400"
          }`}
        >
          <span>{toast.message}</span>
        </div>
      )}

      {loading && (
        <div className="fixed inset-0 bg-background/50 backdrop-blur-[1px] z-50 flex items-center justify-center pointer-events-none">
          <div className="bg-card border border-border px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3">
            <Loader2 className="w-5 h-5 animate-spin text-primary" />
            <span className="text-xs font-semibold text-muted-foreground">Communicating...</span>
          </div>
        </div>
      )}

      <AdminProtected>
        <div className="flex w-full">
          <Sidebar />
          <div className="flex-1 flex flex-col min-h-screen overflow-hidden">
            <Header title={getSectionTitle()} />
            <main className="flex-1 flex flex-col overflow-y-auto">
              <Routes>
                <Route path="/admin" element={<Dashboard />} />
                <Route path="/admin/dashboard" element={<Navigate to="/admin" replace />} />
                <Route path="/admin/knowledge" element={<KnowledgeBase />} />
                <Route path="/admin/knowledge/:documentId" element={<DocumentDetail />} />
                <Route path="/admin/registry" element={<GovRegistry />} />
                <Route path="*" element={<Navigate to="/admin" replace />} />
              </Routes>
            </main>
          </div>
        </div>
      </AdminProtected>
    </div>
  );
}
