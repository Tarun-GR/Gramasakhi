import React from "react";
import { RegisterForm } from "../components/auth/RegisterForm";
import { Landmark, Sun, Moon } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export const Register = () => {
  const { theme, toggleTheme } = useAuth();

  return (
    <div className="min-h-screen flex flex-col justify-between bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-50 transition duration-300 relative overflow-hidden">
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-emerald-400/10 rounded-full blur-3xl pointer-events-none" />

      <header className="px-6 py-4 flex items-center justify-between border-b border-slate-100 dark:border-slate-850 shrink-0 z-10 bg-white/40 dark:bg-slate-950/40 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 bg-emerald-700 text-white rounded-xl flex items-center justify-center">
            <Landmark className="h-5 w-5" />
          </div>
          <span className="font-extrabold text-lg tracking-tight text-emerald-800 dark:text-emerald-300">
            GramSakhi
          </span>
        </div>

        <button
          onClick={toggleTheme}
          className="p-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl"
        >
          {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </button>
      </header>

      <main className="flex-1 flex items-center justify-center p-6 z-10">
        <div className="w-full flex justify-center">
          <RegisterForm />
        </div>
      </main>

      <footer className="py-4 border-t border-slate-100 dark:border-slate-850 text-center text-xs text-slate-400 shrink-0 z-10">
        &copy; {new Date().getFullYear()} GramSakhi. Last-mile governance assistant.
      </footer>
    </div>
  );
};

export default Register;
