import React, { createContext, useContext, useState, useEffect } from "react";
import api, { apiEvents } from "../services/api";

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider");
  return context;
};

export const AuthProvider = ({ children }) => {
  const [citizenAccountId, setCitizenAccountId] = useState(
    () => localStorage.getItem("citizenAccountId") || localStorage.getItem("familyAccountId") || null
  );
  const [phoneNumber, setPhoneNumber] = useState(() => localStorage.getItem("citizenPhone") || null);
  const [globalLoading, setGlobalLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");

  useEffect(() => {
    const unsubLoading = apiEvents.subscribe("loading", (isLoading) => setGlobalLoading(isLoading));
    const unsubToast = apiEvents.subscribe("toast", (msg) => {
      setToastMessage(msg);
      setTimeout(() => setToastMessage(null), 4000);
    });
    return () => {
      unsubLoading();
      unsubToast();
    };
  }, []);

  useEffect(() => {
    if (theme === "dark") document.documentElement.classList.add("dark");
    else document.documentElement.classList.remove("dark");
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme((prev) => (prev === "light" ? "dark" : "light"));

  const showToast = (type, message) => {
    setToastMessage({ type, message });
    setTimeout(() => setToastMessage(null), 4000);
  };

  const handleLoginResponse = (data) => {
    const accountId = data.citizen_account_id || data.family_account_id;
    localStorage.setItem("accessToken", data.accessToken);
    localStorage.setItem("citizenAccountId", accountId);
    localStorage.setItem("familyAccountId", accountId);
    if (data.phone_number) {
      localStorage.setItem("citizenPhone", data.phone_number);
      setPhoneNumber(data.phone_number);
    }
    setCitizenAccountId(accountId);
    showToast("success", "Login successful!");
    return data;
  };

  const loginWithPassword = async (phone, password) => {
    const res = await api.post("/auth/login", {
      phone_number: phone,
      password,
      login_type: "password",
    });
    return handleLoginResponse(res.data);
  };

  const loginWithOtp = async (phone, code) => {
    const res = await api.post("/auth/otp/verify", {
      phone_number: phone,
      code,
    });
    // Existing accounts get a token; brand-new phones only get a verify message.
    if (res.data?.accessToken) {
      return handleLoginResponse(res.data);
    }
    showToast("success", res.data?.message || "OTP verified. Please create your account.");
    return { ...res.data, needs_registration: true, phone_number: phone };
  };

  const registerCitizen = async (registrationData) => {
    const res = await api.post("/auth/register", registrationData);
    showToast("success", "Account created. You can log in now.");
    return res.data;
  };

  const logout = () => {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("citizenAccountId");
    localStorage.removeItem("familyAccountId");
    localStorage.removeItem("citizenPhone");
    localStorage.removeItem("selectedPatient");
    localStorage.removeItem("selectedPatientId");
    setCitizenAccountId(null);
    setPhoneNumber(null);
    showToast("success", "Logged out successfully.");
  };

  const clearToast = () => setToastMessage(null);

  return (
    <AuthContext.Provider
      value={{
        citizenAccountId,
        familyAccountId: citizenAccountId,
        phoneNumber,
        globalLoading,
        toastMessage,
        theme,
        toggleTheme,
        showToast,
        clearToast,
        loginWithPassword,
        loginWithOtp,
        registerCitizen,
        registerPatient: registerCitizen,
        logout,
        // Compatibility stubs so leftover patient UI does not crash if referenced
        patients: [],
        patientsLoaded: true,
        selectedPatient: null,
        selectPatient: () => {},
        refreshPatients: async () => {},
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
