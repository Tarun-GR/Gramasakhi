/** Map POST /auth/otp/send JSON into client otpSession state. */
export function otpSessionFromSendResponse(data) {
  if (!data) return null;
  if (data.delivery_mode === "demo" && data.demo_otp) {
    return {
      deliveryMode: "demo",
      devOtp: data.demo_otp,
      devNotice: data.demo_notice,
      otpVerificationId: data.otp_verification_id,
      expiresInSeconds: data.expires_in_seconds,
      otpLabel: "FYP demo login code",
      ariaLabel: "FYP demonstration OTP",
    };
  }
  if (data.delivery_mode === "dev_popup" && data.dev_otp) {
    return {
      deliveryMode: data.delivery_mode,
      devOtp: data.dev_otp,
      devNotice: data.dev_notice,
      otpVerificationId: data.otp_verification_id,
      expiresInSeconds: data.expires_in_seconds,
    };
  }
  return {
    deliveryMode: data.delivery_mode || "sms",
    otpVerificationId: data.otp_verification_id,
    expiresInSeconds: data.expires_in_seconds,
    devOtp: null,
  };
}
