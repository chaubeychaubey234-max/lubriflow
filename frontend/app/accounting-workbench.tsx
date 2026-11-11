"use client";
import { useState } from "react";
type Row = Record<string, any>;
type Field = [string, string, string, string?];
const forms: Record<
  string,
  { label: string; fields: Field[]; entries?: boolean; allocations?: boolean }
> = {
  bankAdjustment: {
    label: 'Post bank charge / interest / unidentified entry',
    fields: [['statement', 'Unmatched statement', 'bankStatements'],
      ['kind', 'Treatment', 'options', 'charge,interest,unidentified'],
      ['reason', 'Posting explanation', 'text']],
  },
  dubaiAccountingDefaults: {
    label: "Apply Dubai defaults (empty company)",
    fields: [],
  },
  bankCurrency: {
    label: "Set currency of unused bank account",
    fields: [
      ["bankLedger", "Bank / cash", "banks"],
      ["currency", "Currency", "text"],
    ],
  },
  currencyTransfer: {
    label: "Record currency bank transfer",
    fields: [
      ["fromBank", "From bank", "banks"],
      ["toBank", "To bank", "banks"],
      ["date", "Date", "date"],
      ["fromAmount", "Amount sent", "number"],
      ["toAmount", "Amount received", "number"],
      ["fromRate", "Source exchange rate", "number"],
      ["toRate", "Destination exchange rate", "number"],
      ["reference", "Bank reference", "text"],
    ],
  },
  accountingInvoice: {
    label: "Service / non-stock invoice",
    fields: [
      ["side", "Party type", "options", "supplier,customer"],
      ["party", "Party", "parties"],
      ["date", "Date", "date"],
      ["due", "Due date", "date"],
      ["reference", "Invoice reference", "text"],
      ["account", "Expense / revenue account", "accounts"],
      ["amount", "Net amount", "number"],
      ["taxAmount", "Tax amount", "number"],
      ["currency", "Currency", "text"],
      ["rate", "Exchange rate", "number"],
      ["costCentre", "Cost centre", "costCentres"],
      ["project", "Project", "projects"],
      ["reason", "Description", "text"],
    ],
  },
  unmatchBank: {label: "Unmatch bank statement", fields: [["statement", "Matched statement", "bankStatements"], ["date", "Unmatch date", "date"], ["reason", "Reason", "text"]]},
  accountingVoucher: {
    label: "Accounting voucher",
    fields: [
      ["voucherType", "Voucher type", "voucherTypes"],
      ["date", "Posting date", "date"],
      ["reference", "Reference", "text"],
      ["reason", "Narration", "text"],
      ["currency", "Transaction currency", "text"],
      ["rate", "Base currency per foreign unit", "number"],
    ],
    entries: true,
  },
  voucherType: {
    label: "Define voucher type",
    fields: [
      ["name", "Name", "text"],
      [
        "family",
        "Family",
        "options",
        "journal,contra,payment,receipt,sales,purchase,credit,debit,opening",
      ],
    ],
  },
  onAccountCredit: {
    label: "On-account credit note",
    fields: [
      ["side", "Party type", "options", "supplier,customer"],
      ["party", "Party", "parties"],
      ["account", "Expense / revenue account", "accounts"],
      ["date", "Credit date", "date"],
      ["amount", "Net credit", "number"],
      ["taxAmount", "Tax credit", "number"],
      ["currency", "Currency", "text"],
      ["rate", "Exchange rate", "number"],
      ["reference", "Credit note reference", "text"],
      ["reason", "Justification", "text"],
    ],
  },
  partyFunds: {
    label: "Record advance / payment / receipt",
    fields: [
      ["side", "Party type", "options", "supplier,customer"],
      ["party", "Party", "parties"],
      ["date", "Date", "date"],
      ["amount", "Amount in transaction currency", "number"],
      ["currency", "Currency", "text"],
      ["rate", "Base currency per foreign unit", "number"],
      ["bankLedger", "Bank / cash", "banks"],
      ["reference", "External reference", "text"],
    ],
  },
  allocateFunds: {
    label: "Allocate funds to invoices",
    fields: [
      ["fund", "Available funds", "partyFunds"],
      ["date", "Allocation date", "date"],
    ],
    allocations: true,
  },
  refundFunds: {
    label: "Refund unallocated funds / credits",
    fields: [
      ["fund", "Funds or credit", "partyFunds"],
      ["date", "Date", "date"],
      ["amount", "Refund amount", "number"],
      ["rate", "Settlement exchange rate", "number"],
      ["bankLedger", "Bank / cash", "banks"],
      ["reference", "External refund reference", "text"],
      ["reason", "Reason", "text"],
    ],
  },
  financeSchedule: {
    label: "Recurring journal / accrual / prepayment",
    fields: [
      ["name", "Schedule name", "text"],
      ["executionMode", "Execution", "options", "manual,automatic"],
      ["kind", "Schedule kind", "options", "recurring,accrual,prepayment"],
      ["start", "First posting date", "date"],
      ["months", "Number of monthly postings", "number"],
      ["reverseDate", "Accrual reversal date", "date"],
    ],
    entries: true,
  },
  runFinanceSchedules: {
    label: "Post due schedules",
    fields: [["through", "Post through", "date"]],
  },
  resumeFinanceSchedule: {
    label: "Resume held schedule",
    fields: [
      ["id", "Schedule", "financeSchedules"],
      ["reason", "Resolution", "text"],
    ],
  },
  cancelFinanceSchedule: {
    label: "Cancel future schedule postings",
    fields: [
      ["id", "Schedule", "financeSchedules"],
      ["reason", "Reason", "text"],
    ],
  },
  financeBudget: {
    label: "Cost centre / project budget",
    fields: [
      ["account", "Account", "accounts"],
      ["costCentre", "Cost centre", "costCentres"],
      ["project", "Project", "projects"],
      ["start", "Period start", "date"],
      ["end", "Period end", "date"],
      ["amount", "Budget in base currency", "number"],
    ],
  },
  project: { label: "New project", fields: [["name", "Project name", "text"]] },
  reverseVoucher: {
    label: "Reverse accounting voucher",
    fields: [
      ["id", "Voucher", "vouchers"],
      ["date", "Reversal date", "date"],
      ["reason", "Reason", "text"],
    ],
  },
  revalueFX: {
    label: "Revalue foreign invoices",
    fields: [["date", "Revaluation date", "date"]],
  },
  exchangeRate: {
    label: "Exchange rate",
    fields: [
      ["fromCurrency", "From currency", "text"],
      ["toCurrency", "Base currency", "text"],
      ["date", "Effective date", "date"],
      ["rate", "Rate", "number"],
      ["source", "Rate evidence / source", "text"],
    ],
  },
  reviseAsset: {
    label: "Revise future asset depreciation",
    fields: [
      ["id", "Asset", "assets"],
      ["date", "Effective date", "date"],
      ["residual", "Revised residual value", "number"],
      ["remainingMonths", "Remaining useful life (months)", "number"],
      ["reason", "Evidence / reason", "text"],
    ],
  },
  disposeAsset: {
    label: "Dispose of asset",
    fields: [
      ["id", "Asset", "assets"],
      ["date", "Disposal date", "date"],
      ["proceeds", "Net proceeds (base currency)", "number"],
      ["bankLedger", "Bank / cash", "banks"],
      ["reason", "Reason", "text"],
    ],
  },
  classifyCashFlow: {
    label: "Classify cash flow",
    fields: [
      ["id", "Journal", "journal"],
      [
        "classification",
        "Classification",
        "options",
        "Operating,Investing,Financing",
      ],
      ["reason", "Reason", "text"],
    ],
  },
  closeYear: {
    label: "Close financial year",
    fields: [
      ["end", "Year end (must already be locked)", "date"],
      [
        "shortYearReason",
        "Justification if closing a short financial year",
        "text",
      ],
    ],
  },
  enablePerpetual: {
    label: "Activate perpetual inventory accounting",
    fields: [["date", "Opening date", "date"]],
  },
};
const today = () => new Date().toLocaleDateString("en-CA");
export default function AccountingWorkbench({
  state,
  finance,
  busy,
  submit,
}: {
  state: Row;
  finance: Row;
  busy: boolean;
  submit: (a: string, d: Row) => Promise<boolean | undefined>;
}) {
  const [action, setAction] = useState("accountingVoucher");
  const defaults = () => ({
    date: today(),
    through: today(),
    currency: state.settings.currency,
    toCurrency: state.settings.currency,
    side: "supplier",
    executionMode: "manual",
    family: "journal",
    classification: "Operating",
    kind: "recurring",
    months: 12,
    bankLedger: "LED-BANK",
  });
  const [values, setValues] = useState<Row>(defaults);
  const [entries, setEntries] = useState<Row[]>([
    { account: "LED-PUR", debit: 0, credit: 0 },
    { account: "LED-BANK", debit: 0, credit: 0 },
  ]);
  const [allocations, setAllocations] = useState<Row[]>([
    { invoice: "", amount: 0 },
  ]);
  const [notice, setNotice] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const form = forms[action];
  const options = (source: string): Row[] =>
    source === 'bankStatements'
      ? state.bankStatements.filter((row: Row) => action === 'bankAdjustment' ? row.status === 'Unreconciled' : row.status === 'Reconciled')
      : source === "accounts"
      ? finance.accounts
      : source === "banks"
        ? state.ledgers.filter((x: Row) => ["bank", "cash"].includes(x.type))
        : source === "parties"
          ? state[values.side === "customer" ? "customers" : "suppliers"]
          : source === "vouchers"
            ? state.journal.filter((j: Row) => j.accountingVoucher)
            : state[source] || [];
  const select = (
    key: string,
    value: any,
    source: string,
    onChange: (v: string) => void,
  ) => (
    <select
      aria-label={key}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">Choose / optional</option>
      {options(source).map((x) => (
        <option key={x.id} value={x.id}>
          {x.name || x.reference || x.id} — {x.id}
        </option>
      ))}
    </select>
  );
  const change = (key: string, value: any) =>
    setValues((v) => ({ ...v, [key]: value }));
  const fund = (state.partyFunds || []).find((f: Row) => f.id === values.fund);
  const invoices = [
    ...state[fund?.side === "customer" ? "salesInvoices" : "invoices"],
    ...(state.accountingDocuments || []).filter(
      (i: Row) => !fund || i.side === fund.side,
    ),
  ].filter((i: Row) => !fund || i[fund.side] === fund.party);
  return (
    <section className="panel">
      <h2>Accounting workbench</h2>
      {action === 'bankAdjustment' && <p>This posts a balanced journal on the bank statement date and reconciles that entry. Charges go to Bank charges; interest to Bank interest income; unidentified amounts to Unidentified bank entries for later investigation. Base-currency accounts only. To correct it, unmatch the entry, reverse its accounting voucher, then post the replacement. Tax is not calculated by this workflow.</p>}
      <p>
        Amounts are in the selected transaction currency; rates mean
        base-currency units per foreign unit. Payments record external
        transactions and do not send money.
      </p>
      <label>
        Workflow
        <select
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setValues(defaults());
            setNotice("");
          }}
        >
          {Object.entries(forms).map(([key, f]) => (
            <option key={key} value={key}>
              {f.label}
            </option>
          ))}
        </select>
      </label>
      {action === "enablePerpetual" && (
        <p>
          Available only for companies without prior accounting or stock
          transactions. Confirm opening stock costs first. Existing companies
          need a reconciled migration.
        </p>
      )}
      {action === "financeSchedule" && (
        <p>
          Each occurrence posts the entered amounts. For prepayments, book the
          initial prepaid asset separately, then enter the periodic expense
          debit and prepaid-asset credit.
        </p>
      )}
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setNotice("");
          const data = { ...values };
          for (const k of Object.keys(data)) if (data[k] === "") delete data[k];
          if (form.entries)
            data.entries = entries.map((x) => ({
              ...x,
              debit: Number(x.debit || 0),
              credit: Number(x.credit || 0),
            }));
          if (form.allocations)
            data.allocations = allocations.map((x) => ({
              ...x,
              amount: Number(x.amount),
            }));
          if (await submit(action, data))
            setNotice(
              "Posted successfully. Review the journal and reports below.",
            );
        }}
      >
        <div className="form-grid">
          {form.fields.map(([key, label, type, list]) => (
            <label key={key}>
              {label}
              {type === "options" ? (
                <select
                  value={values[key] || list!.split(",")[0]}
                  onChange={(e) => change(key, e.target.value)}
                >
                  {list!.split(",").map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              ) : ["text", "date", "number"].includes(type) ? (
                <input
                  type={type}
                  step={type === "number" ? "any" : undefined}
                  value={values[key] ?? ""}
                  onChange={(e) => change(key, e.target.value)}
                />
              ) : (
                select(label, values[key], type, (v) => change(key, v))
              )}
            </label>
          ))}
        </div>
        {form.entries && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Debit</th>
                  <th>Credit</th>
                  <th>Cost centre</th>
                  <th>Project</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {entries.map((line, i) => (
                  <tr key={i}>
                    <td>
                      {select("Account " + i, line.account, "accounts", (v) =>
                        setEntries((rows) =>
                          rows.map((x, n) =>
                            n === i ? { ...x, account: v } : x,
                          ),
                        ),
                      )}
                    </td>
                    {["debit", "credit"].map((key) => (
                      <td key={key}>
                        <input
                          aria-label={`${key} line ${i + 1}`}
                          type="number"
                          min="0"
                          step="0.01"
                          value={line[key]}
                          onChange={(e) =>
                            setEntries((rows) =>
                              rows.map((x, n) =>
                                n === i ? { ...x, [key]: e.target.value } : x,
                              ),
                            )
                          }
                        />
                      </td>
                    ))}
                    {["costCentre", "project"].map((key) => (
                      <td key={key}>
                        {select(
                          key,
                          line[key],
                          key === "project" ? "projects" : "costCentres",
                          (v) =>
                            setEntries((rows) =>
                              rows.map((x, n) =>
                                n === i ? { ...x, [key]: v } : x,
                              ),
                            ),
                        )}
                      </td>
                    ))}
                    <td>
                      <button
                        type="button"
                        disabled={entries.length <= 2}
                        onClick={() =>
                          setEntries((rows) => rows.filter((_, n) => n !== i))
                        }
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button
              type="button"
              onClick={() =>
                setEntries((rows) => [
                  ...rows,
                  { account: "", debit: 0, credit: 0 },
                ])
              }
            >
              Add journal line
            </button>
          </div>
        )}
        {form.allocations && (
          <div>
            {allocations.map((line, i) => (
              <div className="form-grid" key={i}>
                <label>
                  Invoice
                  <select
                    value={line.invoice}
                    onChange={(e) =>
                      setAllocations((rows) =>
                        rows.map((x, n) =>
                          n === i ? { ...x, invoice: e.target.value } : x,
                        ),
                      )
                    }
                  >
                    <option value="">Choose invoice</option>
                    {invoices.map((inv: Row) => (
                      <option key={inv.id} value={inv.id}>
                        {inv.number} — {inv.id}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Amount
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={line.amount}
                    onChange={(e) =>
                      setAllocations((rows) =>
                        rows.map((x, n) =>
                          n === i ? { ...x, amount: e.target.value } : x,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  disabled={allocations.length <= 1}
                  onClick={() =>
                    setAllocations((rows) => rows.filter((_, n) => n !== i))
                  }
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() =>
                setAllocations((rows) => [...rows, { invoice: "", amount: 0 }])
              }
            >
              Add allocation
            </button>
          </div>
        )}
        <button className="primary" disabled={busy}>
          {busy ? "Saving…" : "Save / post"}
        </button>
        <p role="status">{notice}</p>
      </form>
      <h3>Control account reconciliation</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th>General ledger</th>
              <th>Subledger</th>
              <th>Difference</th>
            </tr>
          </thead>
          <tbody>
            {(finance.reports.reconciliation || []).map((r: Row) => (
              <tr key={r.account}>
                <td>{r.account}</td>
                <td>{r.ledger}</td>
                <td>{r.subledger}</td>
                <td>{r.difference}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Invoice ageing at report end</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Party</th>
              <th>Currency</th>
              <th>Outstanding</th>
              <th>Base value</th>
              <th>Age</th>
            </tr>
          </thead>
          <tbody>
            {(finance.reports.ageing || []).map((r: Row) => (
              <tr key={r.side + r.id}>
                <td>{r.id}</td>
                <td>{r.party}</td>
                <td>{r.currency}</td>
                <td>{r.balance}</td>
                <td>{r.baseBalance}</td>
                <td>{r.bucket}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Budget performance</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th>Cost centre / project</th>
              <th>Budget</th>
              <th>Actual</th>
              <th>Remaining</th>
            </tr>
          </thead>
          <tbody>
            {(finance.reports.budgetPerformance || []).map((r: Row) => (
              <tr key={r.id}>
                <td>{r.account}</td>
                <td>
                  {r.costCentre} {r.project}
                </td>
                <td>{r.amount}</td>
                <td>{r.actual}</td>
                <td>{r.remaining}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Cash movement</h3>
      <p>
        Opening: {finance.reports.cashFlow?.opening} · Movement:{" "}
        {finance.reports.cashFlow?.netMovement} · Exchange effect:{" "}
        {finance.reports.cashFlow?.exchangeEffect} · Closing:{" "}
        {finance.reports.cashFlow?.closing}. Unclassified movements need finance
        review before a statutory cash-flow statement.
      </p>
      <h3>Ledger drilldown</h3>
      <label>
        Filter account
        <input
          value={accountFilter}
          onChange={(e) => setAccountFilter(e.target.value)}
        />
      </label>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Journal / source</th>
              <th>Account</th>
              <th>Debit</th>
              <th>Credit</th>
              <th>Dimensions</th>
            </tr>
          </thead>
          <tbody>
            {(finance.reports.ledgerDrilldown || [])
              .filter((r: Row) =>
                r.account.toLowerCase().includes(accountFilter.toLowerCase()),
              )
              .map((r: Row) => (
                <tr key={r.id}>
                  <td>{r.date}</td>
                  <td>
                    {r.journal} / {r.reference}
                  </td>
                  <td>{r.account}</td>
                  <td>{r.debit || 0}</td>
                  <td>{r.credit || 0}</td>
                  <td>
                    {r.costCentre} {r.project}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
