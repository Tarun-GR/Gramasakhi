import React, { useState } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { MobileInput } from "./MobileInput";
import { Loader2 } from "lucide-react";

const schema = z.object({
  display_name: z.string().min(1, "Name is required"),
  phone_number: z.string().length(10, "Mobile number must be exactly 10 digits"),
  password: z.string().min(8, "Password must be at least 8 characters"),
});

export const RegisterForm = () => {
  const { registerCitizen, showToast } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const [submitting, setSubmitting] = useState(false);
  const prefillPhone =
    location.state?.phone || searchParams.get("phone") || localStorage.getItem("tempPhone") || "";

  const {
    control,
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(schema),
    defaultValues: { display_name: "", phone_number: prefillPhone, password: "" },
  });

  const onSubmit = async (data) => {
    setSubmitting(true);
    try {
      await registerCitizen({
        credentials: {
          phone_number: data.phone_number,
          password: data.password,
        },
        display_name: data.display_name,
      });
      showToast("success", "Account created. Please log in.");
      navigate("/citizen/login");
    } catch (err) {
      const msg = err.response?.data?.detail || "Registration failed.";
      showToast("error", msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="w-full max-w-md bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 shadow-xl rounded-3xl p-6 sm:p-8">
      <div className="text-center mb-6">
        <h2 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Create GramSakhi account</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1.5">
          Register with your mobile number to ask about schemes
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div>
          <label htmlFor="register-display-name" className="text-xs font-bold text-slate-500 uppercase">Full name</label>
          <input
            id="register-display-name"
            {...register("display_name")}
            autoComplete="name"
            className="mt-1 w-full px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-transparent text-sm"
          />
          {errors.display_name && (
            <p id="register-display-name-error" className="text-xs text-red-500 mt-1" role="alert">{errors.display_name.message}</p>
          )}
        </div>

        <Controller
          name="phone_number"
          control={control}
          render={({ field }) => (
            <MobileInput label="Mobile Number" error={errors.phone_number?.message} {...field} />
          )}
        />

        <div>
          <label htmlFor="register-password" className="text-xs font-bold text-slate-500 uppercase">Password</label>
          <input
            id="register-password"
            type="password"
            {...register("password")}
            autoComplete="new-password"
            className="mt-1 w-full px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-transparent text-sm"
          />
          {errors.password && (
            <p id="register-password-error" className="text-xs text-red-500 mt-1" role="alert">{errors.password.message}</p>
          )}
        </div>

        <button
          type="submit"
          disabled={submitting}
          aria-busy={submitting}
          className="w-full py-3 rounded-xl bg-emerald-700 text-white font-semibold text-sm hover:bg-emerald-800 disabled:opacity-60"
        >
          {submitting ? <Loader2 className="h-4 w-4 animate-spin mx-auto" aria-hidden="true" /> : "Create account"}
        </button>
      </form>

      <p className="text-center text-sm text-slate-500 mt-6">
        Already registered?{" "}
        <Link to="/citizen/login" className="text-emerald-700 font-semibold hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
};

export default RegisterForm;
