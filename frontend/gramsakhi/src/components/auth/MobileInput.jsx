import React from "react";
import { Phone } from "lucide-react";

export const MobileInput = React.forwardRef(({ error, label, id, ...props }, ref) => {
  const errorText = typeof error === "string" ? error : error?.message;
  const inputId = id || "mobile-number";

  const handleKeyPress = (e) => {
    if (!/[0-9]/.test(e.key)) {
      e.preventDefault();
    }
  };

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={inputId} className="block text-sm font-semibold text-primary mb-1.5">
          {label}
        </label>
      )}
      <div className="relative rounded-2xl shadow-sm">
        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-on-surface-variant">
          <Phone className="h-5 w-5" />
        </div>
        <div className="absolute inset-y-0 left-10 flex items-center pointer-events-none text-on-surface-variant font-medium text-sm select-none border-r border-surface-variant pr-2">
          +91
        </div>
        <input
          ref={ref}
          id={inputId}
          type="tel"
          maxLength={10}
          onKeyPress={handleKeyPress}
          placeholder="Enter 10-digit mobile"
          aria-invalid={Boolean(errorText)}
          className={`block w-full pl-22 py-3 bg-surface-container-lowest border ${
            errorText
              ? "border-error focus:ring-error/20 focus:border-error"
              : "border-surface-variant focus:ring-primary/20 focus:border-primary"
          } rounded-2xl text-on-surface placeholder:text-outline-variant focus:outline-none focus:ring-2 transition duration-200 text-sm`}
          style={{ paddingLeft: "5.5rem" }}
          {...props}
        />
      </div>
      {errorText && <p className="mt-1 text-xs text-error font-medium">{errorText}</p>}
    </div>
  );
});

MobileInput.displayName = "MobileInput";
