/** In-memory OTP flow phone — avoids placing PII in navigation URLs/deep links. */
let pendingPhone: string | null = null;

export function setOtpFlowPhone(phone: string): void {
  pendingPhone = phone.replace(/\D/g, '').slice(0, 10);
}

export function consumeOtpFlowPhone(): string | null {
  const phone = pendingPhone;
  pendingPhone = null;
  return phone;
}

export function clearOtpFlowPhone(): void {
  pendingPhone = null;
}
