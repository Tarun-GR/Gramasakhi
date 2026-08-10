import React, { useState } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { MobileInput } from "./MobileInput";
import { OTPInput } from "./OTPInput";
import api from "../../services/api";
import { Loader2 } from "lucide-react";

const otpLoginSchema = z.object({
  phone_number: z.string().length(10, "Mobile number must be exactly 10 digits"),
  otp: z.string().length(6, "OTP must be exactly 6 digits"),
});

export const LoginForm = () => {
  const [otpSent, setOtpSent] = useState(false);
  const [sendingOtp, setSendingOtp] = useState(false);
  const { loginWithOtp, showToast } = useAuth();
  const navigate = useNavigate();

  const {
    control,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(otpLoginSchema),
    defaultValues: { phone_number: "", otp: "" },
  });

  const handleSendOtp = async () => {
    const phoneNumber = getValues("phone_number");
    if (!phoneNumber || phoneNumber.length !== 10) {
      showToast("error", "Please enter a valid 10-digit mobile number first.");
      return;
    }
    setSendingOtp(true);
    try {
      const res = await api.post("/auth/otp/send", { phone_number: phoneNumber });
      setOtpSent(true);
      showToast("success", res.data.message || "OTP sent successfully!");
    } catch (err) {
      const msg = err.response?.data?.detail || "Failed to send OTP.";
      showToast("error", msg);
    } finally {
      setSendingOtp(false);
    }
  };

  const onSubmit = async (data) => {
    try {
      const result = await loginWithOtp(data.phone_number, data.otp);
      if (result?.needs_registration) {
        localStorage.setItem("tempPhone", data.phone_number);
        navigate(`/register?phone=${data.phone_number}`);
        return;
      }
      navigate("/");
    } catch (err) {
      const msg = err.response?.data?.detail || "OTP verification failed. Please try again.";
      showToast("error", msg);
    }
  };

  return (
    <div className="w-full max-w-md bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 shadow-xl rounded-3xl p-6 sm:p-8">
      <div className="text-center mb-6">
        <h2 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Welcome to GramSakhi</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1.5">
          Sign in to ask about government schemes
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
        <div>
          <Controller
            name="phone_number"
            control={control}
            render={({ field }) => (
              <MobileInput
                label="Mobile Number"
                error={errors.phone_number?.message}
                {...field}
              />
            )}
          />
        </div>

        {!otpSent ? (
          <button
            type="button"
            onClick={handleSendOtp}
            disabled={sendingOtp}
            className="w-full py-3 rounded-xl bg-emerald-700 text-white font-semibold text-sm hover:bg-emerald-800 disabled:opacity-60"
          >
            {sendingOtp ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : "Send OTP"}
          </button>
        ) : (
          <>
            <Controller
              name="otp"
              control={control}
              render={({ field }) => (
                <OTPInput label="Enter OTP" error={errors.otp?.message} {...field} />
              )}
            />
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3 rounded-xl bg-emerald-700 text-white font-semibold text-sm hover:bg-emerald-800 disabled:opacity-60"
            >
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : "Verify & Continue"}
            </button>
          </>
        )}
      </form>

      <p className="text-center text-sm text-slate-500 mt-6">
        New here?{" "}
        <Link to="/register" className="text-emerald-700 font-semibold hover:underline">
          Create citizen account
        </Link>
      </p>
    </div>
  );
};

export default LoginForm;
