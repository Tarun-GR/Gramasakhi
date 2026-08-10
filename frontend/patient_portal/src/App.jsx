import React, { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import Login from "./pages/Login";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import OTPVerification from "./pages/OTPVerification";
import AskGramSakhi from "./pages/AskGramSakhi";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";

const ProtectedRoute = ({ children }) => {
  const { citizenAccountId } = useAuth();
  if (!citizenAccountId) return <Navigate to="/login" replace />;
  return children;
};

const GuestRoute = ({ children }) => {
  const { citizenAccountId } = useAuth();
  if (citizenAccountId) return <Navigate to="/" replace />;
  return children;
};

const GlobalToast = () => {
  const { toastMessage, clearToast } = useAuth();
  if (!toastMessage) return null;

  const getIcon = () => {
    switch (toastMessage.type) {
      case "success":
        return <CheckCircle2 className="h-5 w-5 shrink-0" />;
      case "error":
        return <AlertCircle className="h-5 w-5 shrink-0" />;
      default:
        return <Info className="h-5 w-5 shrink-0" />;
    }
  };

  return (
    <div className="fixed top-5 right-5 z-55 max-w-sm w-full p-4 border rounded-2xl flex items-start gap-3 shadow-lg animate-in slide-in-from-top-5 duration-300 backdrop-blur-md opacity-98 select-none border-transparent text-white bg-slate-900/90">
      <div className="text-blue-400">{getIcon()}</div>
      <div className="flex-1 text-xs font-semibold leading-relaxed pr-2">{toastMessage.message}</div>
      <button onClick={clearToast} className="text-slate-400 hover:text-white transition focus:outline-none">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
};

export const App = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route
            path="/login"
            element={
              <GuestRoute>
                <Login />
              </GuestRoute>
            }
          />
          <Route
            path="/register"
            element={
              <GuestRoute>
                <Register />
              </GuestRoute>
            }
          />
          <Route
            path="/forgot-password"
            element={
              <GuestRoute>
                <ForgotPassword />
              </GuestRoute>
            }
          />
          <Route path="/verify-otp" element={<OTPVerification />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <AskGramSakhi />
              </ProtectedRoute>
            }
          />
          <Route path="/dashboard" element={<Navigate to="/" replace />} />
          <Route path="/family-selection" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
        <GlobalToast />
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
