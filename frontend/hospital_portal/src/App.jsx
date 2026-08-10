import React from "react";
import { Landmark } from "lucide-react";

/**
 * Hospital portal healthcare UI was removed in Phase 1 (Sahyog → GramSakhi).
 * Clinical modules are preserved under backend/app/_legacy_healthcare for review only.
 */
export default function App() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 text-slate-800 p-6">
      <div className="max-w-md text-center space-y-4">
        <div className="w-12 h-12 mx-auto rounded-xl bg-emerald-700 text-white flex items-center justify-center">
          <Landmark className="w-6 h-6" />
        </div>
        <h1 className="text-2xl font-bold">GramSakhi</h1>
        <p className="text-sm text-slate-600 leading-relaxed">
          The hospital / doctor clinical portal from Sahyog has been retired. Use the citizen
          Ask interface or the GramSakhi Admin knowledge-base portal instead.
        </p>
        <div className="flex flex-col sm:flex-row gap-2 justify-center pt-2">
          <a
            className="px-4 py-2 rounded-lg bg-emerald-700 text-white text-sm font-semibold"
            href="http://localhost:5176/"
          >
            Citizen Ask
          </a>
          <a
            className="px-4 py-2 rounded-lg border border-slate-300 text-sm font-semibold"
            href="http://localhost:5174/login"
          >
            Admin Portal
          </a>
        </div>
      </div>
    </div>
  );
}
