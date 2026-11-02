import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BillsView } from "./BillsView";

const BILL = {
  id: 1,
  period_start: "2026-09-24",
  period_end: "2026-10-23",
  on_peak_kwh: 30,
  off_peak_kwh: 483,
  super_off_peak_kwh: 546,
  total_kwh: 1058,
  current_service: 126.46,
  ecc: 11.02,
  franchise_fee: 1.65,
  sales_tax: 11.13,
  actual_charge: 150.26,
  budget_payment: 248,
  budget_difference: -97.74,
  running_difference: -260.13,
};
const { id: _id, ...DRAFT } = BILL;

type Call = { url: string; method: string; body: any };
let calls: Call[];

function show({
  bills = [BILL],
  compare = { billed_kwh: 1058, measured_kwh: 1000, coverage: 0.98, difference_pct: -5.5 },
  draft = DRAFT as Record<string, unknown>,
  saveStatus = 201,
} = {}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "GET") {
        return new Response(JSON.stringify(url.endsWith("/compare") ? compare : { bills }));
      }
      calls.push({
        url,
        method,
        body: typeof init?.body === "string" ? JSON.parse(init.body) : init?.body,
      });
      if (url === "/api/bills/parse") return new Response(JSON.stringify(draft));
      if (method === "DELETE") return new Response(null, { status: 204 });
      return new Response(JSON.stringify({ id: 2 }), { status: saveStatus });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BillsView />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

const upload = () =>
  fireEvent.change(screen.getByLabelText(/upload a bill/i), {
    target: { files: [new File(["%PDF"], "bill.pdf", { type: "application/pdf" })] },
  });

describe("BillsView", () => {
  it("actual_charge_is_headline_not_budget_payment", async () => {
    show();
    const headline = await screen.findByTestId("bill-headline");
    expect(headline).toHaveTextContent("$150.26");
    expect(headline).not.toHaveTextContent("248");
    expect(screen.getByText(/you paid \$248\.00 on budget billing/i)).toBeInTheDocument();
  });

  it("explains_the_budget_balance_in_words", async () => {
    show();
    expect(await screen.findByText(/\$260\.13 paid ahead/i)).toBeInTheDocument();
  });

  it("bill_without_budget_billing_omits_that_line", async () => {
    show({ bills: [{ ...BILL, budget_payment: null, budget_difference: null, running_difference: null }] as never });
    await screen.findByTestId("bill-headline");
    expect(screen.queryByText(/budget billing/i)).not.toBeInTheDocument();
  });

  it("compare_shows_a_difference_when_coverage_is_good", async () => {
    show();
    expect(await screen.findByText(/1000 kWh measured.*5\.5% below/i)).toBeInTheDocument();
  });

  it("compare_with_gaps_reports_coverage_and_no_difference", async () => {
    show({ compare: { billed_kwh: 1058, measured_kwh: 3, coverage: 0.01, difference_pct: null } as never });
    expect(await screen.findByText(/only 1% of this period was recorded/i)).toBeInTheDocument();
    expect(screen.queryByText(/below/i)).not.toBeInTheDocument();
  });

  it("draft_must_be_confirmed_before_save", async () => {
    show({ bills: [] });
    await screen.findByText(/no bills yet/i);
    upload();
    const save = await screen.findByRole("button", { name: /save this bill/i });
    expect(calls.map((c) => c.url)).toEqual(["/api/bills/parse"]);
    fireEvent.change(screen.getByLabelText(/actual charge/i), { target: { value: "151.00" } });
    fireEvent.click(save);
    await waitFor(() => expect(calls[1]?.url).toBe("/api/bills"));
    expect(calls[1].body.actual_charge).toBe(151);
    expect(calls[1].body.total_kwh).toBe(1058);
    expect(calls[1].body.period_start).toBe("2026-09-24");
  });

  it("unreadable_pdf_opens_a_blank_form_and_says_so", async () => {
    show({ bills: [], draft: {} });
    await screen.findByText(/no bills yet/i);
    upload();
    expect(await screen.findByText(/couldn.t read everything/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/actual charge/i)).toHaveValue(null);
  });

  it("manual_entry_works_without_pdf", async () => {
    show({ bills: [] });
    fireEvent.click(await screen.findByRole("button", { name: /enter by hand/i }));
    fireEvent.change(screen.getByLabelText(/period start/i), { target: { value: "2026-08-25" } });
    fireEvent.change(screen.getByLabelText(/period end/i), { target: { value: "2026-09-23" } });
    fireEvent.change(screen.getByLabelText(/total kwh/i), { target: { value: "1441" } });
    fireEvent.change(screen.getByLabelText(/actual charge/i), { target: { value: "210.5" } });
    fireEvent.click(screen.getByRole("button", { name: /save this bill/i }));
    await waitFor(() => expect(calls[0]?.url).toBe("/api/bills"));
    expect(calls[0].body).toMatchObject({ total_kwh: 1441, actual_charge: 210.5, budget_payment: null });
  });

  it("missing_required_fields_explain_and_save_nothing", async () => {
    show({ bills: [] });
    fireEvent.click(await screen.findByRole("button", { name: /enter by hand/i }));
    fireEvent.click(screen.getByRole("button", { name: /save this bill/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/period.*total kwh.*actual charge/i);
    expect(calls).toHaveLength(0);
  });

  it("same_period_twice_gets_a_clear_message", async () => {
    show({ saveStatus: 409 });
    await screen.findByTestId("bill-headline");
    upload();
    fireEvent.click(await screen.findByRole("button", { name: /save this bill/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already saved/i);
  });

  it("deleting_a_bill_asks_first", async () => {
    show();
    const card = within((await screen.findByTestId("bill-headline")).closest("article")!);
    fireEvent.click(card.getByRole("button", { name: /delete bill/i }));
    expect(calls).toHaveLength(0);
    fireEvent.click(card.getByRole("button", { name: /yes, delete/i }));
    await waitFor(() => expect(calls[0]?.url).toBe("/api/bills/1"));
  });
});
