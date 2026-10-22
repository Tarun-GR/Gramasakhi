import React, { useState, useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { MobileInput } from "./MobileInput";
import api from "../../services/api";
import { otpSessionFromSendResponse } from "../../utils/otpSendSession";
import { Loader2, Presentation } from "lucide-react";

const phoneSchema = z.object({
  phone_number: z.string().length(10, "Mobile number must be exactly 10 digits"),
});

export const LoginForm = () => {
  const [sendingOtp, setSendingOtp] = useState(false);
  const [demoInfo, setDemoInfo] = useState(null);
  const { showToast } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const returnTo = location.state?.from || "/chat";

  const {
    control,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(phoneSchema),
    defaultValues: { phone_number: "" },
  });

  useEffect(() => {
    let cancelled = false;
    api
      .get("/auth/demo/info", { skipErrorToast: true })
      .then((res) => {
        if (!cancelled && res.data?.enabled) setDemoInfo(res.data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const sendOtpForPhone = async (phone_number) => {
    setSendingOtp(true);
    try {
      const res = await api.post("/auth/otp/send", { phone_number }, { skipErrorToast: true });
      localStorage.setItem("tempPhone", phone_number);
      showToast("success", res.data?.message || "OTP sent successfully!");
      const otpSession = otpSessionFromSendResponse(res.data);
      // Phone travels via navigation state + tempPhone, never in the URL
      // (query strings end up in browser history and server access logs).
      navigate("/citizen/verify-otp", {
        state: { from: returnTo, phone: phone_number, otpSession },
      });
    } catch (err) {
      const msg = err.response?.data?.detail || "Failed to send OTP.";
      showToast("error", msg);
    } finally {
      setSendingOtp(false);
    }
  };

  const onSendOtp = async (values) => sendOtpForPhone(values.phone_number);

  const onDemoLogin = async () => {
    if (!demoInfo?.demo_phone || sendingOtp) return;
    setValue("phone_number", demoInfo.demo_phone);
    await sendOtpForPhone(demoInfo.demo_phone);
  };

  return (
    <div className="w-full bg-surface-container-lowest border border-surface-variant shadow-ambient rounded-[32px] p-6 sm:p-8">
      {demoInfo?.enabled && demoInfo.demo_phone && (
        <div className="mb-5 p-4 rounded-2xl border border-secondary/30 bg-secondary-container/40 space-y-3">
          <p className="text-xs text-on-surface-variant leading-snug">{demoInfo.notice}</p>
          <button
            type="button"
            onClick={onDemoLogin}
            disabled={sendingOtp}
            className="w-full py-2.5 rounded-full border-2 border-secondary text-secondary font-bold text-sm hover:bg-secondary-container flex items-center justify-center gap-2 disabled:opacity-60"
          >
            {sendingOtp ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <>
                <Presentation className="h-4 w-4" aria-hidden="true" />
                Use FYP demo login ({demoInfo.label || "demo"})
              </>
            )}
          </button>
        </div>
      )}
      <form onSubmit={handleSubmit(onSendOtp)} className="space-y-5">
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

        <button
          type="submit"
          disabled={sendingOtp}
          aria-busy={sendingOtp}
          className="w-full py-3 rounded-full bg-primary text-on-primary font-bold text-sm hover:bg-surface-tint disabled:opacity-60 transition-all active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          {sendingOtp ? <Loader2 className="h-4 w-4 animate-spin mx-auto" aria-hidden="true" /> : "Send OTP"}
        </button>
      </form>

      <p className="text-center text-sm text-on-surface-variant mt-4">
        New here?{" "}
        <Link
          to="/citizen/register"
          state={{ from: returnTo }}
          className="text-secondary font-bold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 rounded"
        >
          Create citizen account
        </Link>
      </p>
    </div>
  );
};

export default LoginForm;
