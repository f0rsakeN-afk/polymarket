"use client";

import { InputOTP, InputOTPGroup, InputOTPSlot } from "@workspace/ui/components/input-otp";
import { cn } from "@workspace/ui/lib/utils";

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  maxLength?: number;
  error?: boolean;
  autoFocus?: boolean;
  disabled?: boolean;
}

export function OtpInput({
  value,
  onChange,
  maxLength = 6,
  error = false,
  autoFocus = true,
  disabled = false,
}: OtpInputProps) {
  return (
    <div className="flex justify-center">
      <InputOTP
        maxLength={maxLength}
        value={value}
        onChange={onChange}
        autoFocus={autoFocus}
        disabled={disabled}
        render={({ slots }) => (
          <InputOTPGroup>
            {(slots ?? []).map((slot, index) => (
              <InputOTPSlot
                key={index}
                index={index}
                char={slot.char}
                isActive={slot.isActive}
                hasFakeCaret={slot.hasFakeCaret}
                className={cn(
                  "h-12 w-10 text-center text-lg font-semibold",
                  error && "border-destructive data-[state=checked]:border-destructive"
                )}
              />
            ))}
          </InputOTPGroup>
        )}
      />
    </div>
  );
}
