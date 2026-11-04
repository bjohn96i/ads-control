import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { ApiError, getJson, send } from "../api/client";

type Fields = {
  period_start: string | null;
  period_end: string | null;
  on_peak_kwh: number | null;
  off_peak_kwh: number | null;
  super_off_peak_kwh: number | null;
  total_kwh: number | null;
  current_service: number | null;
  ecc: number | null;
  franchise_fee: number | null;
  sales_tax: number | null;
  actual_charge: number | null;
  budget_payment: number | null;
  budget_difference: number | null;
  running_difference: number | null;
};
type Bill = Fields & { id: number; period_start: string; period_end: string; total_kwh: number; actual_charge: number };
type Compare = {
  billed_kwh: number;
  measured_kwh: number;
  coverage: number;
  difference_pct: number | null;
};

const NUMBER_FIELDS: [keyof Fields, string][] = [
  ["total_kwh", "Total kWh"],
  ["actual_charge", "Actual charge ($)"],
  ["on_peak_kwh", "On-peak kWh"],
  ["off_peak_kwh", "Off-peak kWh"],
  ["super_off_peak_kwh", "Super off-peak kWh"],
  ["current_service", "Current service ($)"],
  ["ecc", "Environmental compliance ($)"],
  ["franchise_fee", "Franchise fee ($)"],
  ["sales_tax", "Sales tax ($)"],
  ["budget_payment", "Budget Billing payment ($)"],
  ["budget_difference", "Budget difference this bill ($)"],
  ["running_difference", "Budget running difference ($)"],
];
const EMPTY = Object.fromEntries(
  ["period_start", "period_end", ...NUMBER_FIELDS.map(([k]) => k)].map((k) => [k, ""]),
) as Record<keyof Fields, string>;

const dollars = (value: number) => `$${Math.abs(value).toFixed(2)}`;

function formatDay(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function BudgetLine({ bill }: { bill: Bill }) {
  if (bill.budget_payment === null) return null;
  const running = bill.running_difference;
  return (
    <p className="sub">
      You paid {dollars(bill.budget_payment)} on Budget Billing.
      {running !== null
        ? ` ${dollars(running)} ${running < 0 ? "paid ahead" : "still owed"} overall.`
        : ""}
    </p>
  );
}

function MeterCheck({ billId }: { billId: number }) {
  const { data } = useQuery({
    queryKey: ["bill-compare", billId],
    queryFn: () => getJson<Compare>(`/api/bills/${billId}/compare`),
  });
  if (!data) return null;
  if (data.difference_pct === null) {
    return (
      <p className="sub">
        Can't check against the monitor: only {Math.round(data.coverage * 100)}% of this period was
        recorded.
      </p>
    );
  }
  const direction = data.difference_pct < 0 ? "below" : "above";
  return (
    <p className="sub">
      {Math.round(data.measured_kwh)} kWh measured, {Math.abs(data.difference_pct).toFixed(1)}%{" "}
      {direction} the bill.
    </p>
  );
}

function BillCard({ bill, onDelete }: { bill: Bill; onDelete: (id: number) => void }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <article className="panel task">
      <div className="label">
        {formatDay(bill.period_start)} to {formatDay(bill.period_end)}
      </div>
      <div className="big" data-testid="bill-headline">
        {dollars(bill.actual_charge)}
      </div>
      <p className="sub">Actual charge for {Math.round(bill.total_kwh)} kWh</p>
      {bill.on_peak_kwh !== null ? (
        <p className="sub">
          {Math.round(bill.on_peak_kwh)} on-peak, {Math.round(bill.off_peak_kwh ?? 0)} off-peak,{" "}
          {Math.round(bill.super_off_peak_kwh ?? 0)} super off-peak
        </p>
      ) : null}
      <BudgetLine bill={bill} />
      <MeterCheck billId={bill.id} />
      {confirming ? (
        <div className="confirm">
          <span>Delete this bill?</span>
          <button type="button" className="danger" onClick={() => onDelete(bill.id)}>
            Yes, delete
          </button>
          <button type="button" onClick={() => setConfirming(false)}>
            Keep it
          </button>
        </div>
      ) : (
        <button type="button" className="link danger" onClick={() => setConfirming(true)}>
          Delete bill
        </button>
      )}
    </article>
  );
}

function toForm(draft: Partial<Fields>): Record<keyof Fields, string> {
  const form = { ...EMPTY };
  for (const key of Object.keys(EMPTY) as (keyof Fields)[]) {
    const value = draft[key];
    if (value !== null && value !== undefined) form[key] = String(value);
  }
  return form;
}

export function BillsView() {
  const client = useQueryClient();
  const [form, setForm] = useState<Record<keyof Fields, string> | null>(null);
  const [partial, setPartial] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data, isError } = useQuery({
    queryKey: ["bills"],
    queryFn: () => getJson<{ bills: Bill[] }>("/api/bills"),
  });

  const refresh = () => {
    client.invalidateQueries({ queryKey: ["bills"] });
    client.invalidateQueries({ queryKey: ["bill-latest"] });
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    try {
      const response = await fetch("/api/bills/parse", {
        method: "POST",
        headers: { "X-Control-Action": "1", "Content-Type": "application/pdf" },
        body: file,
      });
      if (!response.ok) throw new ApiError("/api/bills/parse", response.status);
      const draft = toForm(await response.json());
      setForm(draft);
      setPartial(!draft.period_start || !draft.period_end || !draft.total_kwh || !draft.actual_charge);
    } catch {
      setError("Couldn't read that file. You can enter the bill by hand.");
    }
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    if (!form.period_start || !form.period_end || form.total_kwh === "" || form.actual_charge === "") {
      setError("A bill needs its period, total kWh and actual charge.");
      return;
    }
    const body: Record<string, unknown> = {
      period_start: form.period_start,
      period_end: form.period_end,
    };
    for (const [key] of NUMBER_FIELDS) body[key] = form[key] === "" ? null : Number(form[key]);
    try {
      await send("POST", "/api/bills", body);
      setForm(null);
      setError(null);
      refresh();
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) {
        setError("A bill for that period is already saved.");
      } else if (failure instanceof ApiError && failure.status === 422) {
        setError("Some of those values don't look right. Check the dates and amounts.");
      } else {
        setError("Not saved. Check you're on the home Wi-Fi and try again.");
      }
    }
  };

  const remove = async (id: number) => {
    try {
      await send("DELETE", `/api/bills/${id}`);
      setError(null);
      refresh();
    } catch {
      setError("Not deleted. Try again.");
    }
  };

  return (
    <main className="page">
      <header className="top">
        <h1>Bills</h1>
        <span className="meta"><a href="/api/bills/export">Back up the bills</a></span>
      </header>
      <div className="task-actions">
        <label className="upload">
          Upload a bill (PDF)
          <input
            type="file"
            accept="application/pdf"
            onChange={(event) => upload(event.target.files?.[0])}
          />
        </label>
        <button
          type="button"
          onClick={() => {
            setForm({ ...EMPTY });
            setPartial(false);
          }}
        >
          Enter by hand
        </button>
      </div>
      {error ? (
        <p className="warn" role="alert">
          {error}
        </p>
      ) : null}
      {isError ? (
        <p className="warn" role="alert">
          Can't reach the house server
        </p>
      ) : null}
      {form ? (
        <form className="panel task add-task editor" noValidate onSubmit={save}>
          <p className="sub">
            {partial
              ? "Couldn't read everything from that file. Fill in what's missing."
              : "Check these against your bill, then save."}
          </p>
          <label>
            Period start
            <input
              type="date"
              value={form.period_start}
              onChange={(e) => setForm({ ...form, period_start: e.target.value })}
            />
          </label>
          <label>
            Period end
            <input
              type="date"
              value={form.period_end}
              onChange={(e) => setForm({ ...form, period_end: e.target.value })}
            />
          </label>
          {NUMBER_FIELDS.map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                step="any"
                value={form[key]}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              />
            </label>
          ))}
          <div className="task-actions">
            <button type="submit">Save this bill</button>
            <button type="button" className="link" onClick={() => setForm(null)}>
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      <div className="tasks">
        {data?.bills.length === 0 && !form ? <p className="sub">No bills yet.</p> : null}
        {data?.bills.map((bill) => (
          <BillCard key={bill.id} bill={bill} onDelete={remove} />
        ))}
      </div>
    </main>
  );
}
