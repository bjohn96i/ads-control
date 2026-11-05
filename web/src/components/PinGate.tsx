import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";
import { ApiError, getJson, send } from "../api/client";

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Wrong PIN.";
    if (error.status === 429) return `Too many tries. Wait ${error.retryAfter ?? "a few"} seconds.`;
    if (error.status === 400) return "The PIN only works on the secure address (https).";
  }
  return "Couldn't check the PIN. Try again.";
}

export function PinGate({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { data, isError } = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => getJson<{ pin_set: boolean; unlocked: boolean }>("/api/auth/status"),
  });

  if (isError) {
    return (
      <p className="warn" role="alert">
        Can't check the PIN right now. Reload to try again.
      </p>
    );
  }
  if (!data) return null;
  if (data.unlocked) return <>{children}</>;
  if (!data.pin_set) {
    return <p className="sub">No PIN has been set. Run: adscontrol pin set</p>;
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await send("POST", "/api/auth/pin", { pin });
      setError(null);
      client.invalidateQueries({ queryKey: ["auth-status"] });
    } catch (failure) {
      setError(message(failure));
      setPin("");
    }
  };

  return (
    <form className="pin-gate" onSubmit={submit}>
      <label>
        Household PIN
        <input
          type="password"
          inputMode="numeric"
          autoComplete="off"
          value={pin}
          onChange={(event) => setPin(event.target.value)}
        />
      </label>
      <button type="submit">Unlock</button>
      {error ? (
        <p className="warn" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
