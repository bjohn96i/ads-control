import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, send } from "../api/client";
import { PinGate } from "./PinGate";

// The fields /api/climate/summary gives for each thermostat; /api/climate gives them too.
export type ThermostatState = {
  id: number;
  name: string;
  stale: boolean;
  ambient_f: number | null;
  setpoint_f: number | null;
  heat_f: number | null;
  cool_f: number | null;
  mode: string | null;
  hvac_status: string | null;
  eco: boolean;
  online: boolean;
};

export function blocked(t: ThermostatState): string | null {
  if (t.stale) return null;
  if (!t.online) return "This thermostat is offline.";
  if (t.eco) return "This thermostat is in Eco mode. Turn Eco off in the Google Home app to change it here.";
  if (t.mode === "OFF") return "This thermostat is off.";
  return null;
}

function Controls({ t, onError }: { t: ThermostatState; onError: (text: string | null) => void }) {
  const client = useQueryClient();
  const range = t.mode === "HEATCOOL";
  const [target, setTarget] = useState<"heat" | "cool">("heat");
  const current = range ? (target === "heat" ? t.heat_f : t.cool_f) : t.setpoint_f;
  const [choice, setChoice] = useState<number | null>(null);
  const shown = choice ?? (current === null ? null : Math.round(current));
  if (shown === null) return null;

  const save = async () => {
    try {
      await send("POST", `/api/climate/${t.id}/setpoint`, {
        temp_f: shown,
        ...(range ? { target } : {}),
      });
      onError(null);
      setChoice(null);
      client.invalidateQueries({ queryKey: ["climate"] });
      client.invalidateQueries({ queryKey: ["climate-summary"] });
    } catch (failure) {
      onError(
        failure instanceof ApiError && failure.status === 401
          ? "Not changed. Enter the PIN again."
          : "Not changed. Check the thermostat's state and try again.",
      );
    }
  };

  return (
    <div className="task-actions">
      {range ? (
        <>
          <button type="button" aria-pressed={target === "heat"} onClick={() => { setTarget("heat"); setChoice(null); }}>
            Heat
          </button>
          <button type="button" aria-pressed={target === "cool"} onClick={() => { setTarget("cool"); setChoice(null); }}>
            Cool
          </button>
        </>
      ) : null}
      <button type="button" aria-label="Cooler" disabled={shown <= 50} onClick={() => setChoice(shown - 1)}>
        −
      </button>
      <button type="button" aria-label="Warmer" disabled={shown >= 90} onClick={() => setChoice(shown + 1)}>
        +
      </button>
      {choice !== null && choice !== Math.round(current ?? choice) ? (
        <button type="button" onClick={save}>
          Set to {shown}°
        </button>
      ) : null}
    </div>
  );
}

/**
 * The reason a thermostat can't be changed, or its controls behind the PIN. Nothing when stale.
 * gated=false is only for a caller that has already checked the PIN itself (the home A/C card).
 */
export function ThermostatControls({
  t,
  onError,
  gated = true,
}: {
  t: ThermostatState;
  onError: (text: string | null) => void;
  gated?: boolean;
}) {
  if (t.stale) return null;
  const reason = blocked(t);
  if (reason) return <p className="sub">{reason}</p>;
  const controls = <Controls t={t} onError={onError} />;
  return gated ? <PinGate>{controls}</PinGate> : controls;
}
