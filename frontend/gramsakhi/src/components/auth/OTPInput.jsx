import React, { useRef, useState, useEffect } from "react";

export const OTPInput = ({ value = "", onChange, error, label }) => {
  const [digits, setDigits] = useState(Array(6).fill(""));
  const inputRefs = useRef([]);

  // Sync state with incoming value
  useEffect(() => {
    const valString = value ? value.toString() : "";
    const newDigits = Array(6).fill("");
    for (let i = 0; i < Math.min(6, valString.length); i++) {
      newDigits[i] = valString[i];
    }
    setDigits(newDigits);
  }, [value]);

  const handleChange = (index, val) => {
    // Only accept numeric entries
    const numVal = val.replace(/[^0-9]/g, "");
    if (!numVal) {
      const newDigits = [...digits];
      newDigits[index] = "";
      setDigits(newDigits);
      onChange?.(newDigits.join(""));
      return;
    }

    const newDigits = [...digits];
    // If user enters multiple characters (e.g. paste or autocomplete)
    if (numVal.length > 1) {
      const chunk = numVal.split("").slice(0, 6 - index);
      chunk.forEach((char, offset) => {
        newDigits[index + offset] = char;
      });
      setDigits(newDigits);
      const combined = newDigits.join("");
      onChange?.(combined);
      
      const targetIndex = Math.min(5, index + chunk.length);
      inputRefs.current[targetIndex]?.focus();
      return;
    }

    newDigits[index] = numVal;
    setDigits(newDigits);
    onChange?.(newDigits.join(""));

    // Auto-focus next input
    if (index < 5 && numVal) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index, e) => {
    if (e.key === "Backspace") {
      if (!digits[index] && index > 0) {
        // Clear previous input and focus it
        const newDigits = [...digits];
        newDigits[index - 1] = "";
        setDigits(newDigits);
        onChange?.(newDigits.join(""));
        inputRefs.current[index - 1]?.focus();
      } else {
        // Clear current input
        const newDigits = [...digits];
        newDigits[index] = "";
        setDigits(newDigits);
        onChange?.(newDigits.join(""));
      }
    } else if (e.key === "ArrowLeft" && index > 0) {
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === "ArrowRight" && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pasteData = e.clipboardData.getData("text").replace(/[^0-9]/g, "").slice(0, 6);
    if (pasteData) {
      const newDigits = [...digits];
      pasteData.split("").forEach((char, idx) => {
        newDigits[idx] = char;
      });
      setDigits(newDigits);
      onChange?.(newDigits.join(""));
      // Focus last populated input or first empty
      const targetIndex = Math.min(5, pasteData.length - 1);
      inputRefs.current[targetIndex]?.focus();
    }
  };

  const errorText = typeof error === "string" ? error : error?.message;
  const errorId = errorText ? "otp-input-error" : undefined;

  return (
    <div className="w-full">
      <fieldset className="border-0 p-0 m-0" aria-describedby={errorId} aria-invalid={Boolean(errorText)}>
        {label && (
          <legend className="block w-full text-center text-sm font-semibold text-primary mb-2">
            {label}
          </legend>
        )}
        <div className="flex justify-center gap-2.5 sm:gap-3.5" onPaste={handlePaste}>
          {digits.map((digit, idx) => (
            <input
              key={idx}
              type="text"
              inputMode="numeric"
              autoComplete={idx === 0 ? 'one-time-code' : 'off'}
              maxLength={1}
              value={digit}
              ref={(el) => (inputRefs.current[idx] = el)}
              onChange={(e) => handleChange(idx, e.target.value)}
              onKeyDown={(e) => handleKeyDown(idx, e)}
              aria-label={`OTP digit ${idx + 1} of 6`}
              aria-invalid={Boolean(errorText)}
              aria-describedby={errorId}
              className={`w-11 h-14 sm:w-12 sm:h-14 text-center text-xl font-bold bg-surface-container-lowest border ${
                errorText
                  ? "border-error focus:ring-error/20"
                  : "border-surface-variant focus:ring-primary/20 focus:border-primary"
              } rounded-2xl text-on-surface focus:outline-none focus:ring-2 transition duration-200`}
            />
          ))}
        </div>
      </fieldset>
      {errorText && (
        <p id="otp-input-error" className="mt-2 text-center text-xs text-error font-medium" role="alert">
          {errorText}
        </p>
      )}
    </div>
  );
};
