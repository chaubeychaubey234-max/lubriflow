"use client";
import AccountingWorkbench from "./accounting-workbench";
import ProcurementDashboard from "./procurement-dashboard";
import MaterialPlanner from "./material-planner";
import CompanySetup from "./company-setup";
import BankSplit from "./bank-split";
import { useEffect, useState, useCallback, useRef } from "react";
import AccountSecurity from "./security";
import {
  ArrowUpRight,
  ChevronRight,
  Plus,
  Search,
  RefreshCw,
  LogOut,
  Package,
  ClipboardList,
  Settings,
  CheckCircle2,
  LayoutDashboard,
  X,
  Download,
  FileText,
  ShieldCheck,
  Workflow,
  Wallet,
} from "lucide-react";
import {
  forms,
  labels,
  pages,
  Row,
  Field,
  total,
  money,
  localDate,
} from "./forms";

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function companyHeaders(): Record<string, string> {
  const company = sessionStorage.getItem('lubriflow-company');
  return company ? {'X-Lubriflow-Company': company} : {};
}

async function downloadDocument(id: string, name: string) {
  const response = await fetch('/api/documents/' + encodeURIComponent(id), {credentials: 'same-origin', headers: companyHeaders()});
  if (!response.ok) throw new Error('Document access failed. Refresh company access and retry.');
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function api(path: string, body?: unknown, method?: string) {
  if (['/auth/login', '/auth/logout'].includes(path)) sessionStorage.removeItem('lubriflow-company');
  const isFile = body instanceof FormData;
  const response = await fetch("/api" + path, {
    method: method || (body ? "POST" : "GET"),
    credentials: "same-origin",
    headers: {
      ...(!path.startsWith('/auth/') ? companyHeaders() : {}),
      ...(body ? { "X-Lubriflow-Request": "1" } : {}),
      ...(body && !isFile ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? (isFile ? body : JSON.stringify(body)) : undefined,
  });
  const out = await response.json();
  if (!response.ok)
    throw new ApiError(
      typeof out.detail === "string"
        ? out.detail
        : JSON.stringify(out.detail || "Request failed."),
      response.status,
    );
  return out;
}
const permissions: Record<string, string[]> = {
  requester: ["requisition", "comment"],
  buyer: [
    "createRFQ", "closeRFQ", "queueSupplierMessage", "cancelSupplierMessage",
    "supplier",
    "editSupplier",
    "item",
    "editItem",
    "requisition",
    "quote",
    "award",
    "order",
    "editOrder",
    "submit",
    "convert",
    "dispatch",
    "ack",
    "cancel",
    "close",
    "preclose",
    "priceAgreement",
    "comment",
  ],
  approver: ["approvePR", "rejectPR", "approve", "reject", "comment", "approveStockCount"],
  stores: ["receipt", "return", "stockIssue", "stockTransfer", "comment", "stockCount", "reserveStock", "releaseReservation", "relocateStock", "consumeProduction", "finishProduction"],
  production: ["bom", "productionOrder", "releaseProduction", "consumeProduction", "finishProduction", "cancelProduction", "reserveStock", "releaseReservation"],
  quality: ["accept", "rejectReceipt", "comment", "stockDisposition"],
  sales: ["salesOrder", "deliverSale", "salesInvoice", "customerPayment", "comment", "salesQuote", "convertSalesQuote", "salesReturn", "customerCredit", "reserveStock", "releaseReservation", "closeSalesOrder"],
  finance: [
    "landedCost", "customerCredit", "confirmOpeningCost",
    "approve",
    "invoice",
    "editInvoice",
    "voidInvoice",
    "match",
    "post",
    "pay",
    "reversePayment",
    "credit",
    "journal",
    "reverseJournal",
    "account",
    "linkSubmission",
    "rejectSubmission",
    "bankStatement",
    "bankStatementImport",
    "reconcileBank",
    "reconcileBankGroup",
    "asset",
    "depreciate",
    "exchangeRate",
    "taxWorkpaper",
    "closePeriod",
    "closeYear",
    "comment",
  ],
};
const can = (actor: Row | null, action: string) =>
  actor?.role === "admin" || !!permissions[actor?.role || ""]?.includes(action);
const icon = (key: string) =>
  key === "overview" ? (
    <LayoutDashboard size={18} />
  ) : key === "automation" ? (
    <Workflow size={18} />
  ) : key === "settings" ? (
    <Settings size={18} />
  ) : key === "items" ? (
    <Package size={18} />
  ) : key === "books" ? (
    <Wallet size={18} />
  ) : (
    <ClipboardList size={18} />
  );

export default function Workspace() {
  const [sso, setSso] = useState({ enabled: false, passwordEnabled: true });
  useEffect(() => { api("/auth/sso/config").then(setSso).catch(() => {}); }, []);
  const [actor, setActor] = useState<Row | null>(null),
    [state, setState] = useState<Row | null>(null),
    [revision, setRevision] = useState(0),
    [page, setPage] = useState("overview"),
    [search, setSearch] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<{ action: string; data: Row } | null>(
      null,
    ),
    [values, setValues] = useState<Row>({}),
    [detail, setDetail] = useState<Row | null>(null),
    [finance, setFinance] = useState<Row | null>(null),
    [inventory, setInventory] = useState<Row | null>(null),
    [trace, setTrace] = useState<Row | null>(null),
    [runs, setRuns] = useState<Row[]>([]),
    [users, setUsers] = useState<Row[]>([]),
    [memberships, setMemberships] = useState<Row[]>([]),
    [ocr, setOcr] = useState<Row | null>(null),
    [portal, setPortal] = useState<Row | null>(null);
  const [period, setPeriod] = useState({
    start: localDate().slice(0, 4) + "-01-01",
    end: localDate(),
  });
  const [bankMatches, setBankMatches] = useState<Row | null>(null);
  const [companies, setCompanies] = useState<Row[]>([]);
  const [selectedCompany, setSelectedCompany] = useState('');
  const [mfaRequired, setMfaRequired] = useState(false);
  const [bankSelected, setBankSelected] = useState<string[]>([]);
  const [tablePages, setTablePages] = useState<Record<string, number>>({});
  useEffect(() => {setTablePages({}); setBankMatches(null); setBankSelected([]);}, [page, search]);
  const saveGuard = useRef(false),
    searchRef = useRef<HTMLInputElement>(null);
  const refresh = useCallback(async () => {
    try {
      const user = await api("/auth/me");
      setActor(user);
      if (user.role === "supplier") {
        sessionStorage.removeItem('lubriflow-company');
        setPortal(await api("/portal"));
        return;
      }
      const directory = await api('/companies');
      setCompanies(directory.companies);
      let selected = sessionStorage.getItem('lubriflow-company') || '';
      if (!directory.companies.some((company: Row) => company.id === selected)) {
        selected = directory.companies.find((company: Row) => company.current)?.id || '';
        if (selected) sessionStorage.setItem('lubriflow-company', selected);
        else sessionStorage.removeItem('lubriflow-company');
      }
      setSelectedCompany(selected);
      const out = await api("/workspace");
      setActor(out.actor);
      setState(out.state);
      setRevision(out.revision);
      setMfaRequired(false);
    } catch (e) {
      const error = (e as Error).message;
      if (error === 'MFA enrollment required before privileged company access.') setMfaRequired(true);
      if (error === "Sign in required.") setActor(null);
      else setMessage(error);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  useEffect(() => {
    if (!actor || !state) return;
    const run = async () => {
      try {
        if (page === "books")
          setFinance(
            await api("/finance?start=" + period.start + "&end=" + period.end),
          );
        if (page === "automation") setRuns(await api("/automation"));
        if (page === "stockPositions") setInventory(await api("/inventory-report"));
        if (["settings", "orders", "overview"].includes(page) && actor.role === "admin")
          setUsers(await api("/users"));
        if (page === "settings" && actor.role === "admin")
          setMemberships(await api("/companies/members"));
        if (page === "documents" && ["admin", "finance"].includes(actor.role))
          setOcr(await api("/ocr"));
      } catch (e) {
        setMessage((e as Error).message);
      }
    };
    run();
  }, [page, revision, actor?.role, period.start, period.end]);
  const open = (action: string, data: Row = {}) => {
    const today = localDate();
    setValues({
      date: today,
      supplierDate: today,
      tax: state?.settings.defaultTax || 0,
      freight: 0,
      discount: 0,
      creditDays: 30,
      leadDays: 7,
      paymentDays: 30,
      warehouse: "WH-MAIN",
      costCentre: "CC-OPS",
      purchaseLedger: "LED-PUR",
      bankLedger: "LED-BANK",
      fromWarehouse: "WH-MAIN",
      unit: "pcs",
      stock: 0,
      reorder: 0,
      target: 1,
      packSize: 1,
      minOrder: 1,
      active: true,
      collection: "warehouses",
      type: "purchase",
      channel: "email",
      intervalDays: 3,
      maxReminders: 3,
      outputQty: 1,
      conversionCost: 0,
      tracking: "none",
      sourceKind: "salesOrders",
      lines: [{ item: "", qty: 1, price: 0, discount: 0 }],
      entries: [
        { account: "LED-BANK", debit: 0, credit: 0 },
        { account: "SYS-AP", debit: 0, credit: 0 },
      ],
      ...data,
    });
    setDetail(null);
    setModal({ action, data });
    setMessage("");
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setModal(null);
        setDetail(null);
      }
      if (e.altKey && e.key.toLowerCase() === "g") {
        e.preventDefault();
        searchRef.current?.focus();
      }
      if (e.key === "F9") {
        e.preventDefault();
        if (can(actor, e.ctrlKey ? "invoice" : "order"))
          open(e.ctrlKey ? "invoice" : "order");
      }
      if (e.key === "F5") {
        e.preventDefault();
        refresh();
      }
      if (e.ctrlKey && e.key.toLowerCase() === "s" && modal) {
        e.preventDefault();
        document
          .querySelector<HTMLFormElement>("#voucher-form")
          ?.requestSubmit();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [actor, modal, state]);
  const pendingCommand = useRef<{
    signature: string;
    requestId: string;
  } | null>(null);
  async function command(action: string, data: Row, close = true) {
    if (saveGuard.current) return;
    saveGuard.current = true;
    setBusy(true);
    setMessage("");
    const signature = JSON.stringify([action, data]);
    if (pendingCommand.current?.signature !== signature)
      pendingCommand.current = { signature, requestId: crypto.randomUUID() };
    try {
      const out = await api("/workspace", {
        action,
        data,
        requestId: pendingCommand.current.requestId,
        revision,
      });
      setState(out.state);
      setRevision(out.revision);
      if (close) setModal(null);
      setDetail(null);
      setMessage("Saved successfully.");
      pendingCommand.current = null;
      return true;
    } catch (e) {
      setMessage((e as Error).message);
      if (e instanceof ApiError && e.status < 500)
        pendingCommand.current = null;
      return false;
    } finally {
      saveGuard.current = false;
      setBusy(false);
    }
  }
  async function task(fn: () => Promise<unknown>) {
    if (saveGuard.current) return;
    saveGuard.current = true;
    setBusy(true);
    setMessage("");
    try {
      await fn();
      await refresh();
      setMessage("Completed successfully.");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      saveGuard.current = false;
      setBusy(false);
    }
  }
  function selectField(key: string, value: string) {
    setValues((old) => {
      const next = { ...old, [key]: value };
      if (key === "supplier") {
        const supplier = state?.suppliers.find((v: Row) => v.id === value);
        if (supplier)
          Object.assign(next, {
            paymentDays: supplier.creditDays,
            paymentTerms: supplier.terms,
            contact: supplier.contact,
            due: addDays(old.date || localDate(), supplier.leadDays),
            billingAddress: state?.settings.address,
            deliveryAddress:
              state?.warehouses.find((w: Row) => w.id === old.warehouse)
                ?.address || "",
          });
      }
      if (["po", "receipt", "invoice"].includes(key)) {
        const source = state?.[
          key === "po" ? "orders" : key === "receipt" ? "receipts" : "invoices"
        ].find((v: Row) => v.id === value);
        if (source) {
          const po =
            key === "po"
              ? source
              : state?.orders.find((o: Row) => o.id === source.po);
          Object.assign(next, {
            lines: source.lines.map((l: Row) => ({ ...l })),
            tax: po?.tax || 0,
            freight: 0,
            amount: total(source),
            due: addDays(old.date || localDate(), po?.paymentDays || 30),
          });
        }
      }
      return next;
    });
  }
  function itemLine(index: number, itemId: string) {
    const item = state?.items.find((v: Row) => v.id === itemId);
    if (!item) return;
    const agreement = state?.prices.find(
      (p: Row) =>
        p.item === itemId &&
        p.supplier === values.supplier &&
        p.validFrom <= (values.date || localDate()) &&
        p.validUntil >= (values.date || localDate()),
    );
    const previous = state?.orders
      .filter(
        (o: Row) =>
          o.supplier === values.supplier &&
          [
            "Approved",
            "Issued",
            "Acknowledged",
            "Part received",
            "Received",
            "Closed",
          ].includes(o.status),
      )
      .flatMap((o: Row) => o.lines)
      .find((l: Row) => l.item === itemId);
    const source = agreement || previous || item;
    setValues((v) => ({
      ...v,
      lines: v.lines.map((l: Row, i: number) =>
        i === index
          ? {
              ...l,
              item: itemId,
              price: source.price,
              discount: source.discount || 0,
              taxRate: source.taxRate ?? item.taxRate,
              description: item.specification,
            }
          : l,
      ),
    }));
  }
  const name = (collection: string, id: string) =>
    state?.[collection]?.find((r: Row) => r.id === id)?.name || id;
  function actions(collection: string, r: Row) {
    const list: [string, string, Row?][] = [];
    if (collection === "items") list.push(["itemTracking", "Tracking / barcode", {item: r.id, tracking: r.tracking || "none", barcode: r.barcode || ""}]);
    if (collection === "stockPositions") list.push(["stockCount", "Count", {position: r.id, counted: r.qty}], ["reserveStock", "Reserve", {position: r.id}]);
    if (collection === "stockPositions") {
      list.push(["stockDisposition", "Quarantine / release", {position: r.id, status: r.status}]);
      if (r.costBasis === "Provisional opening item price" && r.version === 0) list.push(["confirmOpeningCost", "Confirm opening cost", {position: r.id, value: r.value}]);
    }
    if (collection === "stockCounts" && r.status === "Pending") list.push(["approveStockCount", "Approve variance"]);
    if (collection === "reservations" && r.status === "Active") list.push(["releaseReservation", "Release"]);
    if (collection === "salesQuotes" && r.status === "Open") list.push(["convertSalesQuote", "Convert to order"]);
    if (collection === "salesOrders" && r.status === "Open") list.push(["deliverSale", "Deliver", {order: r.id, lines: r.lines}], ["salesInvoice", "Invoice", {order: r.id, lines: r.lines}], ["closeSalesOrder", "Close"]);
    if (collection === "deliveries") list.push(["salesReturn", "Return goods", {delivery: r.id}]);
    if (collection === "salesReturns") list.push(["customerCredit", "Credit return", {return: r.id, qty: r.qty}]);
    if (collection === "salesInvoices") list.push(["customerPayment", "Record receipt", {invoice: r.id}]);
    if (collection === "productionOrders") {
      if (r.status === "Draft") list.push(["releaseProduction", "Release"]);
      if (["Released", "In progress"].includes(r.status)) {
        const remaining = r.lines.map((l: Row) => ({...l, qty: Number(l.qty) - (r.consumption || []).filter((c: Row) => c.item === l.item).reduce((n: number, c: Row) => n + Number(c.qty), 0)})).filter((l: Row) => l.qty > 0);
        if (remaining.length) list.push(["consumeProduction", "Consume materials", {id: r.id, lines: remaining}]);
        list.push(["finishProduction", "Post production output", {id: r.id, outputQty: Number(r.qty) - Number(r.outputQty || 0)}]);
      }
      if (["Draft", "Released"].includes(r.status)) list.push(["cancelProduction", "Cancel"]);
    }
    if (collection === "suppliers") list.push(["supplierMessaging", "Messaging permission", {supplier: r.id}]);
    if (collection === "rfqs" && r.status === "Open") {
      list.push(["queueSupplierMessage", "Send RFQ", {source: r.id, purpose: "rfq"}], ["closeRFQ", "Close"]);
      list.push(["quote", "Record response", {supplier: r.supplier, rfq: r.id, lines: r.lines}]);
    }
    if (collection === "orders" && ["Approved", "Issued", "Acknowledged", "Part received"].includes(r.status)) list.push(["queueSupplierMessage", "Send to supplier", {source: r.id, purpose: "po"}]);
    if (collection === "communications" && ["Queued", "Retry"].includes(r.status)) list.push(["cancelSupplierMessage", "Cancel"]);
    if (collection === "suppliers") {
      list.push(
        ["editSupplier", "Edit", r],
        [
          "approveSupplier",
          "Review qualification",
          { id: r.id, approved: r.approved, qualificationUntil: r.qualificationUntil || "", reason: "" },
        ],
      );
    }
    if (collection === "items")
      list.push(
        ["editItem", "Edit", r],
        ["stockIssue", "Issue stock", { item: r.id }],
        ["stockTransfer", "Transfer", { item: r.id }],
      );
    if (collection === "requisitions") {
      if (r.status === "Pending")
        list.push(["approvePR", "Approve"], ["rejectPR", "Reject"]);
      if (r.status === "Approved") list.push(["convert", "Create POs"]);
    }
    if (collection === "quotes" && r.status === "Received")
      list.push(["award", "Award"]);
    if (collection === "orders") {
      if (r.status === "Draft") list.push(["submit", "Submit"]);
      if (r.status === "Pending approval")
        list.push(["approve", "Approve stage"], ["reject", "Reject"]);
      if (r.status === "Pending approval" && actor?.role === "admin") {
        list.push(["delegateApproval", "Assign substitute", {id: r.id, validHours: 24}]);
        if (r.approvalDelegate) list.push(["revokeApprovalDelegation", "Revoke substitute"]);
      }
      if (r.status === "Approved") list.push(["dispatch", "Record dispatch"]);
      if (r.status === "Issued") list.push(["ack", "Acknowledge"]);
      if (
        ["Issued", "Acknowledged", "Part received", "Received"].includes(
          r.status,
        )
      )
        list.push(
          ["receipt", "Receive", { po: r.id, lines: r.lines }],
          [
            "invoice",
            "Enter bill",
            { po: r.id, lines: r.lines, tax: r.tax, amount: total(r) },
          ],
          ["preclose", "Preclose", { id: r.id, lines: r.lines }],
        );
      if (r.status === "Received") list.push(["close", "Close order"]);
      if (!["Closed", "Cancelled"].includes(r.status))
        list.push(["editOrder", "Amend", r], ["cancel", "Cancel"]);
    }
    if (collection === "receipts") {
      if (["Inspection hold", "Quality hold"].includes(r.status))
        list.push(
          ["accept", "Accept inspection"],
          ["rejectReceipt", "Reject inspection"],
        );
      if (r.status === "Accepted")
        list.push(["return", "Return", { receipt: r.id, lines: r.lines }]);
    }
    if (collection === "invoices") {
      if (["Pending match", "Exception", "Matched"].includes(r.status))
        list.push(
          ["editInvoice", "Edit", r],
          ["match", "Match"],
          ["voidInvoice", "Void"],
        );
      if (r.status === "Matched") list.push(["post", "Post"]);
      if (["Posted", "Part paid"].includes(r.status))
        list.push(
          ["pay", "Record payment"],
          ["credit", "Credit", { invoice: r.id, lines: r.lines }],
        );
    }
    if (collection === "payments" && r.status !== "Reversed")
      list.push(["reversePayment", "Reverse"]);
    if (
      collection === "journal" &&
      r.manual &&
      !state?.journal.some((j: Row) => j.reversalOf === r.id)
    )
      list.push(["reverseJournal", "Reverse"]);
    if (
      collection === "portalSubmissions" &&
      r.status === "Awaiting finance review"
    )
      list.push(
        [
          "invoice",
          "Prepare voucher",
          {
            po: r.po,
            number: r.number,
            amount: r.amount,
            lines: state?.orders.find((o: Row) => o.id === r.po)?.lines || [],
          },
        ],
        ["linkSubmission", "Link voucher"],
        ["rejectSubmission", "Reject"],
      );
    return list
      .filter(([a]) => can(actor, a))
      .map(([action, label, data]) => (
        <button
          key={action}
          className="small"
          disabled={busy}
          onClick={() =>
            forms[action]
              ? open(action, data || { id: r.id })
              : command(action, data || { id: r.id })
          }
        >
          {label}
        </button>
      ));
  }
  function rowsTable(collection: string, rows: Row[]) {
    const filtered = rows.filter((r) =>
      JSON.stringify(r).toLowerCase().includes(search.toLowerCase()),
    );
    const tableKey = `${page}:${collection}`;
    const pageCount = Math.max(1, Math.ceil(filtered.length / 50));
    const currentPage = Math.min(tablePages[tableKey] || 0, pageCount - 1);
    const visible = filtered.slice(currentPage * 50, (currentPage + 1) * 50);
    return (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Reference / name</th>
              <th>Date / supplier</th>
              <th>Status</th>
              <th className="numeric">Value / quantity</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.id}>
                <td>
                  <button
                    className="link"
                    onClick={() => setDetail({ ...r, _collection: collection })}
                  >
                    {r.name || r.number || r.id}
                  </button>
                  <small>
                    {r.name || r.number ? r.id : r.note || r.action || ""}
                  </small>
                </td>
                <td>
                  {r.supplier
                    ? name("suppliers", r.supplier)
                    : r.date || r.at?.slice(0, 10) || r.actor || "—"}
                  <small>{r.po || r.reference || ""}</small>
                </td>
                <td>
                  <span
                    className={
                      "badge " +
                      (r.status === "Exception" || r.status === "Rejected"
                        ? "danger"
                        : "")
                    }
                  >
                    {r.status ||
                      (r.approved !== undefined
                        ? r.approved && (!r.qualificationUntil || r.qualificationUntil >= localDate())
                          ? "Qualified"
                          : r.approved ? "Qualification expired" : "Unqualified"
                        : r.active !== undefined
                          ? r.active
                            ? "Active"
                            : "Inactive"
                          : "Recorded")}
                  </span>
                </td>
                <td className="numeric">
                  {collection === "items"
                    ? `${r.stock} ${r.unit}`
                    : r.amount !== undefined
                      ? money(r.amount)
                      : r.lines
                        ? money(total(r))
                        : r.price !== undefined
                          ? money(r.price)
                          : "—"}
                </td>
                <td>
                  <div className="row-actions">
                    {collection === "drafts" ? (
                      <button
                        onClick={() =>
                          open(r.kind, {
                            ...r.values,
                            id: r.record || undefined,
                          })
                        }
                      >
                        Resume draft
                      </button>
                    ) : (
                      actions(collection, r)
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length > 50 && <nav aria-label={`${collection} pages`} className="row-actions">
          <button disabled={currentPage === 0} onClick={() => setTablePages(p => ({...p, [tableKey]: currentPage - 1}))}>Previous</button>
          <span>Page {currentPage + 1} of {pageCount} · {filtered.length} records</span>
          <button disabled={currentPage + 1 >= pageCount} onClick={() => setTablePages(p => ({...p, [tableKey]: currentPage + 1}))}>Next</button>
        </nav>}
        {!filtered.length && (
          <div className="empty">
            <FileText />
            <h3>No records to show</h3>
            <p>Create your first entry or adjust the search.</p>
          </div>
        )}
      </div>
    );
  }
  function field(field: Field) {
    const key = field.key;
    const val = values[key] ?? "";
    if (field.type === "lines")
      return (
        <div className="full" key={key}>
          <h3>Item lines</h3>
          <label>Scan item barcode / SKU and press Enter
            <input aria-label="Scan item barcode" onKeyDown={async e => {
              if (e.key !== "Enter") return;
              e.preventDefault();
              const code = e.currentTarget.value;
              e.currentTarget.value = "";
              await task(async () => {
                const result = await api("/barcode?code=" + encodeURIComponent(code));
                const item = result.item;
                setValues(v => {
                  const lines = [...(v.lines || [])];
                  const existing = lines.findIndex((l: Row) => l.item === item.id);
                  if (existing >= 0) lines[existing] = {...lines[existing], qty: Number(lines[existing].qty) + 1};
                  else { const blank = lines.findIndex((l: Row) => !l.item); const line = {item: item.id, qty: 1, price: item.price, discount: 0, taxRate: item.taxRate}; if (blank >= 0) lines[blank] = line; else lines.push(line); }
                  return {...v, lines};
                });
              });
            }} />
          </label>
          <div className="line-scroll">
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Quantity</th>
                  <th>Rate</th>
                  <th>Discount %</th>
                  <th>Tax %</th>
                  <th>Bin / lot / serial / reservation</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(values.lines || []).map((line: Row, index: number) => (
                  <tr key={index}>
                    <td>
                      <select
                        aria-label="Item"
                        required
                        value={line.item}
                        onChange={(e) => itemLine(index, e.target.value)}
                      >
                        <option value="">Choose item</option>
                        {state?.items.map((i: Row) => (
                          <option key={i.id} value={i.id}>
                            {i.name} · {i.unit}
                          </option>
                        ))}
                      </select>
                    </td>
                    {["qty", "price", "discount", "taxRate"].map((k) => (
                      <td key={k}>
                        <input
                          aria-label={k}
                          type="number"
                          min={k === "qty" ? "0.000001" : "0"}
                          step={k === "qty" ? "0.000001" : "0.01"}
                          value={line[k] ?? ""}
                          onChange={(e) =>
                            setValues((v) => ({
                              ...v,
                              lines: v.lines.map((l: Row, n: number) =>
                                n === index
                                  ? {
                                      ...l,
                                      [k]:
                                        e.target.value === ""
                                          ? undefined
                                          : Number(e.target.value),
                                    }
                                  : l,
                              ),
                            }))
                          }
                        />
                      </td>
                    ))}
                    <td>
                      <select aria-label="Line bin" value={line.bin || ""} onChange={e => setValues(v => ({...v, lines: v.lines.map((l: Row, n: number) => n === index ? {...l, bin: e.target.value} : l)}))}>
                        <option value="">Unassigned / automatic pick</option>
                        {state?.bins.map((b: Row) => <option key={b.id} value={b.id}>{b.name} · {name("warehouses", b.warehouse)}</option>)}
                      </select>
                      {["lot", "serial", "expiry", "reservation"].map(k => <input key={k} aria-label={"Line " + k} placeholder={k} type={k === "expiry" ? "date" : "text"} value={line[k] || ""} onChange={e => setValues(v => ({...v, lines: v.lines.map((l: Row, n: number) => n === index ? {...l, [k]: e.target.value} : l)}))} />)}
                    </td>
                    <td>
                      <button
                        type="button"
                        aria-label="Remove line"
                        onClick={() =>
                          setValues((v) => ({
                            ...v,
                            lines: v.lines.filter(
                              (_: Row, n: number) => n !== index,
                            ),
                          }))
                        }
                      >
                        <X size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            type="button"
            className="small"
            onClick={() =>
              setValues((v) => ({
                ...v,
                lines: [
                  ...v.lines,
                  { item: "", qty: 1, price: 0, discount: 0 },
                ],
              }))
            }
          >
            Add item line
          </button>
          <strong className="total">
            Calculated total {money(total(values))}
          </strong>
          <p className="hint">
            Rates prefill from a valid agreement, last approved purchase, or
            item master. Review the remaining quantities before saving.
          </p>
        </div>
      );
    if (field.type === "journal")
      return (
        <div className="full" key={key}>
          {(values.entries || []).map((line: Row, n: number) => (
            <div className="journal-row" key={n}>
              <select
                aria-label="Account"
                value={line.account}
                onChange={(e) =>
                  setValues((v) => ({
                    ...v,
                    entries: v.entries.map((l: Row, i: number) =>
                      i === n ? { ...l, account: e.target.value } : l,
                    ),
                  }))
                }
              >
                {finance?.accounts.map((a: Row) => (
                  <option value={a.id} key={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              {["debit", "credit"].map((k) => (
                <input
                  key={k}
                  aria-label={k}
                  placeholder={k}
                  type="number"
                  step=".01"
                  min="0"
                  value={line[k]}
                  onChange={(e) =>
                    setValues((v) => ({
                      ...v,
                      entries: v.entries.map((l: Row, i: number) =>
                        i === n ? { ...l, [k]: e.target.value } : l,
                      ),
                    }))
                  }
                />
              ))}
            </div>
          ))}
          <button
            type="button"
            onClick={() =>
              setValues((v) => ({
                ...v,
                entries: [
                  ...v.entries,
                  { account: "LED-BANK", debit: 0, credit: 0 },
                ],
              }))
            }
          >
            Add journal line
          </button>
        </div>
      );
    return (
      <label key={key} className={field.type === "textarea" ? "full" : ""}>
        {field.label}
        {field.type === "checkbox" ? (
          <input
            type="checkbox"
            checked={!!val}
            onChange={(e) =>
              setValues((v) => ({ ...v, [key]: e.target.checked }))
            }
          />
        ) : field.type === "select" || field.type === "options" ? (
          <select
            value={val}
            onChange={(e) => selectField(key, e.target.value)}
          >
            <option value="">Choose…</option>
            {(field.options || (field.source === "approvalUsers" ? users.filter(u => u.active) : key === "bankLedger" ? state?.ledgers.filter((l: Row) => l.active !== false && ["bank", "cash"].includes(l.type)) : state?.[field.source || ""]) || []).map(
              (r: Row | string) =>
                typeof r === "string" ? (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ) : (
                  <option key={r.id} value={r.id}>
                    {r.name || r.number || r.id}
                    {r.status ? " · " + r.status : ""}
                  </option>
                ),
            )}
          </select>
        ) : field.type === "textarea" ? (
          <textarea
            value={val}
            onChange={(e) =>
              setValues((v) => ({ ...v, [key]: e.target.value }))
            }
          />
        ) : (
          <input
            type={field.type || "text"}
            step="any"
            value={val}
            onChange={(e) =>
              setValues((v) => ({
                ...v,
                [key]:
                  field.type === "number" && e.target.value !== ""
                    ? Number(e.target.value)
                    : e.target.value,
              }))
            }
          />
        )}
      </label>
    );
  }
  if (loading) return <main className="loading">Loading LubriFlow…</main>;
  if (actor && mfaRequired) return <main className="panel"><h1>Secure your company access</h1><p>Enable two-step verification to use your administrator or finance role.</p><AccountSecurity /><button onClick={() => refresh()}>Continue after setup</button><button onClick={async () => {await api('/auth/logout', {}); window.location.reload();}}>Sign out</button></main>;
  if (!actor)
    return (
      <main className="login">
        <div className="login-art">
          <span className="brand-mark">LF</span>
          <h1>
            Control every
            <br />
            purchase.
          </h1>
          <p>From the first request to the final receipt.</p>
          <div className="login-rule" />
          <span>PROCUREMENT · INVENTORY · FINANCE</span>
        </div>
        <form
          className="login-card"
          onSubmit={async (e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            setBusy(true);
            try {
              await api("/auth/login", Object.fromEntries(data));
              setLoading(true);
              await refresh();
              setMessage("");
            } catch (err) {
              setMessage((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <span className="eyebrow">LUBRIFLOW WORKSPACE</span>
          <h2>Welcome back</h2>
          <p>Sign in with your company account.</p>
          {sso.enabled && <a className="primary" href="/api/auth/sso/login">Continue with company SSO</a>}
          {sso.passwordEnabled && <>
          <label>
            Email
            <input name="email" type="email" autoComplete="username" required />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            Authenticator or recovery code (if enabled)
            <input
              name="code"
              maxLength={100}
              autoComplete="one-time-code"
              spellCheck={false}
            />
          </label>
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
            <ArrowUpRight size={18} />
          </button>
          </>}
          {message && (
            <p role="alert" className="error">
              {message}
            </p>
          )}
          <small>Your administrator manages company access.</small>
        </form>
      </main>
    );
  if (actor.role === "supplier")
    return (
      <main className="portal">
        <header>
          <h1>{portal?.company} · Supplier portal</h1>
          <button
            onClick={() =>
              task(async () => {
                await api("/auth/logout", {});
                setActor(null);
              })
            }
          >
            Sign out
          </button>
        </header>
        <p>{portal?.supplier} · Your orders and invoice submissions</p>
        <AccountSecurity />
        {message && (
          <p role="status" className="notice">
            {message}
          </p>
        )}
        {portal?.orders.map((o: Row) => (
          <section className="panel" key={o.id}>
            <h2>
              {o.id} <span className="badge">{o.status}</span>
            </h2>
            <p>
              Delivery {o.due} · {o.paymentTerms}
            </p>
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Quantity</th>
                  <th>Price</th>
                </tr>
              </thead>
              <tbody>
                {o.lines.map((l: Row) => (
                  <tr key={l.item}>
                    <td>{l.name}</td>
                    <td>
                      {l.qty} {l.unit}
                    </td>
                    <td>{money(l.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {o.status === "Issued" && !o.response && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const data = Object.fromEntries(
                    new FormData(e.currentTarget),
                  );
                  task(() =>
                    api("/portal", {
                      action: "respond",
                      data: { po: o.id, ...data },
                      revision: portal.revision,
                      requestId: crypto.randomUUID(),
                    }),
                  );
                }}
              >
                <label>
                  Decision
                  <select name="decision">
                    <option value="accept">Accept order</option>
                    <option value="decline">Decline order</option>
                  </select>
                </label>
                <label>
                  Reason / note
                  <input name="note" />
                </label>
                <button disabled={busy}>Send response</button>
              </form>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const data = Object.fromEntries(new FormData(e.currentTarget));
                task(() =>
                  api("/portal", {
                    action: "submitInvoice",
                    data: { po: o.id, ...data },
                    revision: portal.revision,
                    requestId: crypto.randomUUID(),
                  }),
                );
              }}
            >
              <h3>Submit invoice for review</h3>
              <div className="grid">
                <label>
                  Invoice reference
                  <input name="number" required />
                </label>
                <label>
                  Total
                  <input
                    name="amount"
                    type="number"
                    step=".01"
                    min=".01"
                    required
                  />
                </label>
                <label>
                  Notes
                  <input name="note" />
                </label>
              </div>
              <button disabled={busy}>Submit for finance review</button>
            </form>
          </section>
        ))}
        <section className="panel">
          <h2>Submitted invoices</h2>
          {portal?.submissions.map((s: Row) => (
            <p key={s.id}>
              {s.number} · {money(s.amount)} · {s.status} {s.reviewNote}
            </p>
          ))}
        </section>
      </main>
    );
  if (!state)
    return (
      <main>
        <p role="alert">{message || "Unable to load workspace."}</p>
        <button onClick={refresh}>Retry</button>
      </main>
    );
  const current = pages[page];
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">LF</span>
          <div>
            LubriFlow<small>PURCHASING WORKSPACE</small>
          </div>
        </div>
        <div className="company">
          <span className="avatar">
            {state.settings.company.slice(0, 2).toUpperCase()}
          </span>
          <div>
            {state.settings.company}
            <small>{state.settings.currency || "Currency"} · {state.settings.country || "Global"}</small>
          </div>
        </div>
        <nav>
          {companies.length > 1 && <label>Company<select value={selectedCompany} disabled={busy || !!modal || !!detail} onChange={e => {
            sessionStorage.setItem('lubriflow-company', e.target.value);
            window.location.reload();
          }}>{companies.map(company => <option key={company.id} value={company.id}>{company.name} · {company.role}</option>)}</select></label>}
          {Object.entries(pages)
            .filter(
              ([k]) =>
                k === "procurementInsights" ? ["admin", "buyer", "approver", "finance"].includes(actor.role) : !["books", "automation"].includes(k) ||
                can(actor, k === "books" ? "journal" : "settings"),
            )
            .map(([key, p]) => (
              <button
                key={key}
                className={page === key ? "active" : ""}
                onClick={() => {
                  setPage(key);
                  setSearch("");
                }}
              >
                {icon(key)}
                {p.title}
                <ChevronRight size={13} />
              </button>
            ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />{" "}
          {state.settings.mode === "automatic"
            ? "Automation enabled"
            : "Manual processing"}
          <small>Policy controls apply to every entry</small>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} /> {current.title}
          </div>
          <div className="top-actions">
            <button
              className="icon-button"
              title="Refresh · F5"
              onClick={refresh}
            >
              <RefreshCw size={16} />
            </button>
            <span className="user">
              {actor.name}
              <small>{actor.role}</small>
            </span>
            <button
              className="icon-button"
              aria-label="Sign out"
              onClick={() =>
                task(async () => {
                  await api("/auth/logout", {});
                  setActor(null);
                  setState(null);
                })
              }
            >
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">{localDate()} · COMPANY WORKSPACE</span>
              <h1>{current.title}</h1>
              <p>{current.sub}</p>
            </div>
            {current.create && can(actor, current.create) && (
              <button className="primary" onClick={() => open(current.create!)}>
                <Plus size={17} />
                New {labels[current.create]}
              </button>
            )}
          </div>
          {page === "bankStatements" && can(actor, "bankStatementImport") && <section className="panel row-actions">
            <button disabled={busy} onClick={() => open("bankStatementImport", {bankLedger: "LED-BANK", statementCurrency: state.settings.currency, openingBalance: ""})}>Import statement CSV</button>
            <button onClick={() => setPage("books")}>Review suggested payment matches in Financial books</button>
          </section>}
          {["orders", "overview"].includes(page) && ["admin", "finance", "approver"].includes(actor.role) && state.orders.some((o: Row) => o.status === "Pending approval" && o.approvalEscalation) && (
            <section className="panel"><h2>Overdue approvals</h2>
              {state.orders.filter((o: Row) => o.status === "Pending approval" && o.approvalEscalation).map((o: Row) => (
                <div className="list-row" key={o.id}><span>{o.id} · Escalated to {o.approvalEscalation.role} · Due {new Date(o.approvalDueAt).toLocaleString()}</span>
                  <button onClick={() => setDetail({...o, _collection: "orders"})}>Review order</button>
                </div>
              ))}
            </section>
          )}
          {message && (
            <div role="status" className="notice">
              {message}
              <button
                aria-label="Dismiss message"
                onClick={() => setMessage("")}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {page === "overview" && (
            <>
              <div className="stats">
                {[
                  [
                    "Open commitments",
                    money(
                      state.orders
                        .filter(
                          (o: Row) =>
                            !["Closed", "Cancelled"].includes(o.status),
                        )
                        .reduce((n: number, o: Row) => n + total(o), 0),
                    ),
                  ],
                  [
                    "Awaiting approval",
                    state.orders.filter(
                      (o: Row) => o.status === "Pending approval",
                    ).length,
                  ],
                  [
                    "Inspection holds",
                    state.receipts.filter(
                      (r: Row) => ["Inspection hold", "Quality hold"].includes(r.status),
                    ).length,
                  ],
                  [
                    "Invoice exceptions",
                    state.invoices.filter((i: Row) => i.status === "Exception")
                      .length,
                  ],
                ].map(([label, value]) => (
                  <section key={label} className="stat">
                    <small>{label}</small>
                    <strong>{value}</strong>
                    <span>Current workspace</span>
                  </section>
                ))}
              </div>
              <section className="panel">
                <div className="section-heading">
                  <h2>Work requiring attention</h2>
                  <ShieldCheck size={20} />
                </div>
                {rowsTable(
                  "orders",
                  state.orders
                    .filter(
                      (o: Row) =>
                        o.status === "Pending approval" ||
                        (!["Closed", "Cancelled", "Received"].includes(
                          o.status,
                        ) &&
                          o.due < localDate()),
                    )
                    .slice(0, 10),
                )}
              </section>
              <div className="two-column">
                <section className="panel">
                  <h2>Quick entry</h2>
                  <div className="quick-grid">
                    {["requisition", "order", "receipt", "invoice"]
                      .filter((a) => can(actor, a))
                      .map((a) => (
                        <button key={a} onClick={() => open(a)}>
                          <Plus size={18} />
                          {labels[a]}
                        </button>
                      ))}
                  </div>
                </section>
                <section className="panel">
                  <h2>Replenishment watch</h2>
                  {state.items
                    .filter((i: Row) => i.stock < i.reorder)
                    .map((i: Row) => (
                      <div className="list-row" key={i.id}>
                        <div>
                          {i.name}
                          <small>
                            {i.stock} {i.unit} on hand · reorder at {i.reorder}
                          </small>
                        </div>
                        <span className="badge danger">Low stock</span>
                      </div>
                    ))}
                  {!state.items.some((i: Row) => i.stock < i.reorder) && (
                    <p className="muted">No items below their reorder point.</p>
                  )}
                </section>
              </div>
            </>
          )}
          {current.collection && (
            <section className="panel">
              <div className="section-heading">
                <div className="search">
                  <Search size={16} />
                  <input
                    ref={searchRef}
                    aria-label="Search records"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search records · Alt G"
                  />
                </div>
                <button
                  className="small"
                  onClick={() =>
                    downloadCSV(current.collection!, state[current.collection!])
                  }
                >
                  <Download size={15} />
                  Export CSV
                </button>
              </div>
              {rowsTable(current.collection, state[current.collection])}
            </section>
          )}
          {page === "communications" && (
            <section className="panel">
              <h2>Supplier communication controls</h2>
              <p>Automatic messages require automatic processing mode, this policy enabled, an authorised supplier contact, and configured live providers. Manual queueing works in either mode.</p>
              <p>Accepted means the provider accepted the message. Email delivery is not confirmed by SMTP acceptance. Uncertain messages require provider-log review and are never automatically resent.</p>
              <p>Policy: {state.settings.supplierMessaging?.enabled ? "Enabled" : "Disabled"} · Channel: {state.settings.supplierMessaging?.channel || "email"}</p>
              {can(actor, "messagingPolicy") && <button onClick={() => open("messagingPolicy", state.settings.supplierMessaging || {})}>Configure automation</button>}
              {can(actor, "supplierMessaging") && <button onClick={() => open("supplierMessaging")}>Supplier permissions</button>}
            </section>
          )}
          {page === "stockPositions" && inventory && <section className="panel">
            <h2>Available stock and cost</h2><p>{inventory.method} · Total recorded value: {money(inventory.value)} {state.settings.currency}</p>
            <div className="table-wrap"><table><thead><tr><th>Position / item</th><th>Warehouse / bin</th><th>Lot / serial</th><th>Expiry</th><th>On hand</th><th>Reserved</th><th>Available</th><th>Value</th><th>Trace</th></tr></thead><tbody>
              {inventory.positions.map((p: Row) => <tr key={p.id}><td>{p.id}<br />{name("items", p.item)}</td><td>{name("warehouses", p.warehouse)} / {name("bins", p.bin) || "Unassigned"}</td><td>{p.lot || "—"} / {p.serial || "—"}</td><td>{p.expiry || "—"}</td><td>{p.qty}</td><td>{p.reserved}</td><td>{p.available}</td><td>{money(p.value)}</td><td><button onClick={() => task(async () => setTrace(await api(`/stock-trace?item=${encodeURIComponent(p.item)}&lot=${encodeURIComponent(p.lot)}&serial=${encodeURIComponent(p.serial)}`)))}>Trace</button></td></tr>)}
            </tbody></table></div>
            {trace && <><h3>Movements</h3>{rowsTable("stockMoves", trace.movements)}<h3>Linked production</h3>{rowsTable("productionOrders", trace.production)}<h3>Component and output movements</h3>{rowsTable("stockMoves", trace.genealogy)}<h3>Customer deliveries</h3>{rowsTable("deliveries", trace.deliveries)}<h3>Supplier receipts</h3>{rowsTable("receipts", trace.receipts)}</>}
            <p>Opening costs imported from item prices are provisional. Reconcile them before relying on valuation. These operational values are separate from general-ledger inventory accounting.</p>
          </section>}
          {page === "books" && (
            <>
              <div className="toolbar">
                <label>
                  From
                  <input
                    type="date"
                    value={period.start}
                    onChange={(e) =>
                      setPeriod((v) => ({ ...v, start: e.target.value }))
                    }
                  />
                </label>
                <label>
                  To
                  <input
                    type="date"
                    value={period.end}
                    onChange={(e) =>
                      setPeriod((v) => ({ ...v, end: e.target.value }))
                    }
                  />
                </label>
                <button onClick={() => open("account")}>New account</button>
                <button className="primary" onClick={() => open("journal")}>
                  New journal
                </button>
                <button onClick={() => open("asset")}>Capitalise asset</button>
                <button onClick={() => open("depreciate")}>Depreciation</button>
                <button onClick={() => open("taxWorkpaper")}>Tax workpaper</button>
                <button onClick={() => open("closePeriod")}>Close period</button>
              </div>
              {finance && (
                <>
                  <AccountingWorkbench state={state} finance={finance} busy={busy} submit={(a,d)=>command(a,d,false)} />
                  <div className="stats">
                    {Object.entries(finance.reports.profitAndLoss).map(
                      ([key, val]) => (
                        <section className="stat" key={key}>
                          <small>{key}</small>
                          <strong>{money(val)}</strong>
                        </section>
                      ),
                    )}
                    <section className="stat">
                      <small>Trial balance difference</small>
                      <strong>
                        {money(finance.reports.balanceDifference)}
                      </strong>
                    </section>
                  </div>
                  <section className="panel">
                    <h2>Trial balance</h2>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Account</th>
                            <th>Type</th>
                            <th>Opening</th>
                            <th>Debit</th>
                            <th>Credit</th>
                            <th>Closing</th>
                          </tr>
                        </thead>
                        <tbody>
                          {finance.reports.trial.map((a: Row) => (
                            <tr key={a.id}>
                              <td>{a.name}</td>
                              <td>{a.type}</td>
                              <td>{money(a.opening)}</td>
                              <td>{money(a.debit)}</td>
                              <td>{money(a.credit)}</td>
                              <td>{money(a.closing)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="hint">
                      Statements reflect recorded entries. Opening balances,
                      sales and adjustments must be complete before relying on
                      these reports.
                    </p>
                  </section>
                  <section className="panel">
                    <h2>Balance sheet</h2>
                    <div className="stats">
                      {Object.entries(finance.reports.balanceSheet).map(
                        ([key, val]) => (
                          <div key={key}>
                            <small>{key}</small>
                            <strong>{money(val)}</strong>
                          </div>
                        ),
                      )}
                    </div>
                  </section>
                  <section className="panel">
                    <h2>Journal register</h2>
                    {rowsTable("journal", state.journal)}
                  </section>
                  <section className="panel">
                    <h2>Open payables</h2>
                    {rowsTable(
                      "invoices",
                      finance.reports.payables.filter(
                        (i: Row) => i.balance > 0,
                      ),
                    )}
                  </section>
                  <section className="panel">
                    <h2>Open receivables</h2>
                    {rowsTable("salesInvoices", finance.reports.receivables.filter((i: Row) => i.balance > 0))}
                  </section>
                  <section className="panel">
                    <h2>Bank reconciliation</h2>
                    <BankSplit state={state} busy={busy} command={command} />
                    <button disabled={busy} onClick={() => open("bankStatementImport", {bankLedger: "LED-BANK", statementCurrency: state.settings.currency, openingBalance: ""})}>Import statement CSV</button>
                    <div className="stats">
                      <div><small>Statement debits</small><strong>{money(finance.reports.bankReconciliation.statementDebits)}</strong></div>
                      <div><small>Statement credits</small><strong>{money(finance.reports.bankReconciliation.statementCredits)}</strong></div>
                    </div>
                    {rowsTable("bankStatements", finance.reports.bankReconciliation.unreconciled)}
                    <label>Find possible payment matches<select disabled={busy} value={bankMatches?.statement || ""} onChange={e => {
                      const id = e.target.value;
                      setBankMatches(null);
                      setBankSelected([]);
                      if (id) task(async () => setBankMatches(await api(`/bank-match-suggestions/${encodeURIComponent(id)}`)));
                    }}><option value="">Choose an unmatched statement line</option>{finance.reports.bankReconciliation.unreconciled.map((r: Row) => <option key={r.id} value={r.id}>{r.date} · {r.reference} · {r.amount}</option>)}</select></label>
                    {bankMatches && <div>
                      <p>{bankMatches.candidates.length ? "Select one or more recorded transactions. Nothing is matched until the selected total equals the statement." : "No eligible recorded payment found within seven days."}</p>
                      {bankMatches.ambiguous && <p>More than one exact combination is possible. Confirm the correct transactions.</p>}
                      {bankMatches.candidates.map((r: Row) => {
                        const key = `${r.collection}:${r.transaction}`;
                        return <label key={key} className="check"><input type="checkbox" disabled={busy} checked={bankSelected.includes(key)} onChange={e => setBankSelected(old => e.target.checked ? [...old, key] : old.filter(item => item !== key))}/><span>{r.date} · {r.transaction} · {r.reference || "No reference"} · {money(r.amount)}</span></label>;
                      })}
                      {bankMatches.candidates.length > 0 && (() => {
                        const selected = bankMatches.candidates.filter((r: Row) => bankSelected.includes(`${r.collection}:${r.transaction}`));
                        const total = selected.reduce((sum: number, r: Row) => sum + Number(r.amount || 0), 0);
                        const exact = Math.abs(total - Number(bankMatches.statementAmount || 0)) < 0.000001;
                        return <div><p>Selected {money(total)} of {money(bankMatches.statementAmount)}</p><button disabled={busy || !exact} onClick={async () => {
                          const saved = await command("reconcileBankGroup", {statement: bankMatches.statement, matches: selected.map((r: Row) => ({collection: r.collection, transaction: r.transaction}))}, false);
                          if (saved) {setBankMatches(null); setBankSelected([]);}
                        }}>Reconcile selected transactions</button></div>;
                      })()}
                    </div>}
                  </section>
                  <section className="panel">
                    <h2>Fixed asset register</h2>
                    {rowsTable("assets", finance.reports.fixedAssets)}
                  </section>
                </>
              )}
            </>
          )}
          {page === "productionOrders" && state.settings.modules.manufacturing && ["admin", "production"].includes(actor.role) && <MaterialPlanner state={state} revision={revision} busy={busy} api={api} command={command} />}
          {page === "procurementInsights" && <ProcurementDashboard state={state} actor={actor} revision={revision} busy={busy} api={api} command={command} />}
          {page === "automation" && (
            <>
              <section className="panel">
                <div className="section-heading">
                  <h2>Workflow runner</h2>
                  <button
                    className="primary"
                    disabled={busy || state.settings.mode !== "automatic"}
                    onClick={() =>
                      task(async () => {
                        await api("/automation", {});
                        setRuns(await api("/automation"));
                      })
                    }
                  >
                    Queue automation run
                  </button>
                </div>
                <p>
                  Runs execute the saved replenishment, conversion, approval and
                  matching rules. Human approvals remain in the purchase
                  workflow whenever policy requires them.
                </p>
                <div className="list-row">
                  <span>Processing mode</span>
                  <strong>{state.settings.mode}</strong>
                </div>
                {["autoReorder", "autoPO", "autoApprove", "autoMatch"].map(
                  (k) => (
                    <div key={k} className="list-row">
                      <span>{k}</span>
                      <span className="badge">
                        {state.settings[k] ? "Enabled" : "Disabled"}
                      </span>
                    </div>
                  ),
                )}
                <p className="hint">
                  The background worker must be running for queued and scheduled
                  work. Automatic cycles run every five minutes.
                </p>
              </section>
              <section className="panel">
                <div className="section-heading">
                  <h2>Run history</h2>
                  <button
                    onClick={() =>
                      task(async () => setRuns(await api("/automation")))
                    }
                  >
                    Refresh runs
                  </button>
                </div>
                {runs.map((r) => (
                  <div key={r.id} className="run">
                    <strong>{r.status}</strong>
                    <span>{r.createdAt}</span>
                    <small>{r.id}</small>
                    <p>{r.result?.completed ?? 0} completed actions</p>
                    {r.result?.skipped?.map((s: string, i: number) => (
                      <p className="hint" key={i}>
                        {s}
                      </p>
                    ))}
                    {r.result?.error && (
                      <p className="error">{r.result.error}</p>
                    )}
                  </div>
                ))}
                {!runs.length && (
                  <p className="muted">No automation runs yet.</p>
                )}
              </section>
            </>
          )}
          {page === "documents" && (
            <>
              <section className="panel">
                <h2>Document library</h2>
                <p>
                  Attach PDF, PNG or JPEG files from a voucher’s detail view.
                  Maximum file size is 10 MB.
                </p>
                {state.attachments.map((d: Row) => (
                  <div className="list-row" key={d.id}>
                    <div>
                      <button disabled={busy} onClick={() => task(() => downloadDocument(d.id, d.name))}>{d.name}</button>
                      <small>
                        {d.target} · {(d.size / 1024).toFixed(1)} KB
                      </small>
                    </div>
                    {["admin", "finance"].includes(actor.role) && (
                      <button
                        disabled={
                          busy ||
                          !ocr?.configured ||
                          [
                            "Starting",
                            "Failed / outcome unknown",
                            "Ready for review",
                            "Failed",
                          ].includes(d.ocr?.status)
                        }
                        onClick={() =>
                          task(() =>
                            api("/ocr", {
                              document: d.id,
                              action: d.ocr ? "poll" : "start",
                            }),
                          )
                        }
                      >
                        {d.ocr?.status || "Extract invoice"}
                      </button>
                    )}
                  </div>
                ))}
                {!state.attachments.length && (
                  <p className="muted">No documents attached.</p>
                )}
              </section>
              {["admin", "finance"].includes(actor.role) && (
                <section className="panel">
                  <h2>Invoice extraction review</h2>
                  <p>
                    {ocr?.configured
                      ? "Extraction sends the chosen document to your configured Azure resource. Review the results before voucher entry."
                      : "OCR is not connected. Ask your administrator to configure the provider credentials."}
                  </p>
                  {ocr?.jobs
                    .filter((j: Row) => j.fields)
                    .map((j: Row) => (
                      <article className="run" key={j.document}>
                        <h3>{j.name}</h3>
                        {Object.entries(j.fields).map(([key, v]) => (
                          <div className="list-row" key={key}>
                            <span>{key}</span>
                            <span>
                              {String((v as Row).value)} ·{" "}
                              {Math.round(((v as Row).confidence || 0) * 100)}%
                            </span>
                          </div>
                        ))}
                        <button
                          onClick={() =>
                            open("invoice", {
                              number: j.fields.InvoiceId?.value || "",
                              amount: j.fields.InvoiceTotal?.value || 0,
                              supplierDate:
                                j.fields.InvoiceDate?.value || localDate(),
                              due: j.fields.DueDate?.value || "",
                            })
                          }
                        >
                          Prefill voucher for review
                        </button>
                      </article>
                    ))}
                </section>
              )}
            </>
          )}
          {page === "settings" && (
            <>
              {actor.role === 'admin' && <CompanySetup settings={state.settings} busy={busy} command={command} />}
              <AccountSecurity />
              <section className="panel">
                <h2>Account security</h2>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const data = Object.fromEntries(
                      new FormData(e.currentTarget),
                    );
                    task(async () => {
                      await api("/auth/password", data);
                      setActor(null);
                      setState(null);
                    });
                  }}
                >
                  <div className="grid">
                    <label>
                      Current password
                      <input
                        name="current_password"
                        type="password"
                        required
                        autoComplete="current-password"
                      />
                    </label>
                    <label>
                      New password
                      <input
                        name="new_password"
                        type="password"
                        minLength={12}
                        maxLength={128}
                        required
                        autoComplete="new-password"
                      />
                    </label>
                    <label>
                      Authenticator or recovery code (if enabled)
                      <input
                        name="code"
                        maxLength={100}
                        autoComplete="one-time-code"
                        spellCheck={false}
                      />
                    </label>
                  </div>
                  <button disabled={busy}>
                    Change password and sign out all sessions
                  </button>
                </form>
              </section>
              <section className="panel">
                <h2>Company and policy</h2>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const fd = new FormData(e.currentTarget);
                    const d: Row = Object.fromEntries(fd);
                    for (const k of [
                      "autoPO",
                      "autoApprove",
                      "autoMatch",
                      "autoReorder",
                      "separation",
                    ])
                      d[k] = fd.has(k);
                    d.modules = Object.fromEntries(
                      Object.keys(state.settings.modules || {}).map((module) => [
                        module,
                        fd.has(`module-${module}`),
                      ]),
                    );
                    for (const k of [
                      "limit",
                      "financeThreshold",
                      "budgetMonthly",
                      "priceTolerance",
                      "invoiceTolerance",
                      "defaultTax",
                      "paymentDays",
                    ])
                      d[k] = Number(d[k]);
                    command("settings", d);
                  }}
                >
                  <div className="grid">
                    {[
                      "company",
                      "address",
                      "phone",
                      "email",
                      "legalEntityType",
                      "industryTemplate",
                      "taxRegistrationStatus",
                      "timezone",
                      "fiscalYearStart",
                    ].map((k) => (
                      <label key={k}>
                        {k}
                        <input
                          name={k}
                          defaultValue={state.settings[k]}
                          disabled={actor.role !== "admin"}
                        />
                      </label>
                    ))}
                    <label>
                      Processing mode
                      <select
                        name="mode"
                        defaultValue={state.settings.mode}
                        disabled={actor.role !== "admin"}
                      >
                        <option value="manual">Manual</option>
                        <option value="automatic">Automatic</option>
                      </select>
                    </label>
                    {[
                      "limit",
                      "financeThreshold",
                      "budgetMonthly",
                      "priceTolerance",
                      "invoiceTolerance",
                      "paymentDays",
                    ].map((k) => (
                      <label key={k}>
                        {k}
                        <input
                          name={k}
                          type="number"
                          step="any"
                          defaultValue={state.settings[k]}
                          disabled={actor.role !== "admin"}
                        />
                      </label>
                    ))}
                    {[
                      "autoPO",
                      "autoApprove",
                      "autoMatch",
                      "autoReorder",
                      "separation",
                    ].map((k) => (
                      <label className="check-label" key={k}>
                        <input
                          name={k}
                          type="checkbox"
                          defaultChecked={state.settings[k]}
                          disabled={actor.role !== "admin"}
                        />
                        {k}
                      </label>
                    ))}
                  </div>
                  <p className={state.settings.onboardingCompleted ? "success" : "warning"}>{state.settings.onboardingCompleted ? "Company setup is complete. Country and industry rules can still be refined through configuration packages." : "Complete company, country, legal entity, industry and tax settings to finish onboarding."}</p>
                  <h3>Enabled modules</h3>
                  <div className="grid">
                    {Object.entries(state.settings.modules || {}).map(
                      ([module, enabled]) => (
                        <label className="check-label" key={module}>
                          <input
                            name={`module-${module}`}
                            type="checkbox"
                            defaultChecked={Boolean(enabled)}
                            disabled={actor.role !== "admin" || ["procurement", "inventory", "accounting"].includes(module)}
                          />
                          {module}
                        </label>
                      ),
                    )}
                  </div>
                  {actor.role === "admin" && (
                    <button className="primary" disabled={busy}>
                      Save company controls
                    </button>
                  )}
                </form>
              </section>
              {actor.role === "admin" && <section className="panel">
                <h2>Sensitive finance and tax settings</h2>
                <p>These settings require a request and approval by a different administrator or finance reviewer.</p>
                <form onSubmit={e => {e.preventDefault(); const d = Object.fromEntries(new FormData(e.currentTarget)); command('requestSettingsChange', {changes: {taxId: d.taxId, country: d.country, currency: d.currency, taxRegime: d.taxRegime, defaultTax: Number(d.defaultTax), lockedThrough: d.lockedThrough}, reason: d.reason});}}>
                  <div className="grid">
                    <label>Tax registration number<input name="taxId" defaultValue={state.settings.taxId} /></label>
                    <label>Country code<input name="country" defaultValue={state.settings.country} maxLength={2} /></label>
                    <label>Base currency<input name="currency" defaultValue={state.settings.currency} maxLength={3} /></label>
                    <label>Tax regime<input name="taxRegime" defaultValue={state.settings.taxRegime} /></label>
                    <label>Default tax percentage<input name="defaultTax" type="number" step="any" defaultValue={state.settings.defaultTax} /></label>
                    <label>Lock period through<input name="lockedThrough" type="date" defaultValue={state.settings.lockedThrough} /></label>
                    <label>Reason<input name="reason" required /></label>
                  </div>
                  <button disabled={busy}>Request review</button>
                </form>
                {(state.settingsChangeRequests || []).filter((r: Row) => r.status === 'Pending').map((r: Row) => <div className="list-row" key={r.id}><span>{r.id} · requested by {r.requestedBy} · {r.reason}</span><button disabled={busy || r.requestedBy === actor.id} onClick={() => {const reason = window.prompt('Approval reason'); if (reason) command('approveSettingsChange', {id: r.id, reason});}}>Approve</button></div>)}
              </section>}
              {actor.role === "admin" && <section className="panel">
                <h2>Company access</h2>
                <p>Give an existing active employee access to this company only. Their role in other companies is unchanged.</p>
                <form onSubmit={(e) => { e.preventDefault(); const data = Object.fromEntries(new FormData(e.currentTarget)); task(async () => { await api('/companies/members', data); setMemberships(await api('/companies/members')); (e.currentTarget as HTMLFormElement).reset(); }); }}>
                  <div className="grid">
                    <label>Employee email<input name="email" type="email" required autoComplete="off" /></label>
                    <label>Company role<select name="role" defaultValue="viewer"><option value="admin">Administrator</option><option value="buyer">Buyer</option><option value="requester">Requester</option><option value="approver">Approver</option><option value="stores">Stores</option><option value="quality">Quality</option><option value="production">Production</option><option value="sales">Sales</option><option value="finance">Finance</option><option value="viewer">Viewer</option></select></label>
                  </div>
                  <button className="primary" disabled={busy}>Grant or update access</button>
                </form>
                <div className="list">
                  {memberships.map((member: Row) => <div className="list-row" key={member.id}><span>{member.name} · {member.email} · {member.role} · {member.active ? 'Active' : 'Revoked'}{member.explicit ? '' : ' · inherited home-company access'}</span>{member.explicit && member.active && member.id !== actor.id && <button disabled={busy} onClick={() => task(async () => { await api('/companies/members/' + encodeURIComponent(member.id) + '/revoke', {}); setMemberships(await api('/companies/members')); })}>Revoke</button>}</div>)}
                </div>
              </section>}
              {actor.role === "admin" && (
                <>
                  <section className="panel">
                    <h2>Bank statement column mappings</h2>
                    <p>Save reusable mappings for bank CSV files. Required source headers are date, reference, money in and money out equivalents.</p>
                    {(state.settings.bankImportMappings || []).map((m: Row) => <div className="list-row" key={m.id}><span>{m.name} · delimiter “{m.delimiter === "\t" ? "TAB" : m.delimiter}”</span></div>)}
                    <form onSubmit={e => {e.preventDefault(); const d = Object.fromEntries(new FormData(e.currentTarget)); command("bankImportMapping", {name: d.name, delimiter: d.separator, dateFormat: d.dateFormat, decimalSeparator: d.decimalSeparator, thousandsSeparator: d.thousandsSeparator, columns: {date: d.date, reference: d.reference, money_in: d.money_in, money_out: d.money_out, description: d.description, balance: d.balance}});}}>
                      <div className="grid">
                        <label>Decimal separator<select name="decimalSeparator"><option value=".">Dot: 1234.56</option><option value=",">Comma: 1234,56</option></select></label>
                        <label>Thousands separator<select name="thousandsSeparator"><option value="">None</option><option value=",">Comma: 1,234</option><option value=".">Dot: 1.234</option><option value=" ">Space: 1 234</option></select></label>
                        <label>Date format<select name="dateFormat"><option>YYYY-MM-DD</option><option>DD/MM/YYYY</option><option>MM/DD/YYYY</option></select></label>
                        <label>File separator<select name="separator"><option value=",">Comma (CSV)</option><option value=";">Semicolon</option><option value={'\t'}>Tab (TSV)</option><option value="|">Pipe</option></select></label>
                        {[["name", "Mapping name", "bank-export"], ["date", "Date header", "date"], ["reference", "Reference header", "reference"], ["money_in", "Money-in header", "credit"], ["money_out", "Money-out header", "debit"], ["description", "Description header", "description"], ["balance", "Balance header", "balance"]].map(([key, label, value]) => <label key={key}>{label}<input name={key} defaultValue={value} maxLength={100} required={!["description", "balance"].includes(key)} /></label>)}
                      </div>
                      <button className="primary" disabled={busy}>Save column mapping</button>
                    </form>
                  </section>
                  <section className="panel">
                    <div className="section-heading">
                      <h2>Masters</h2>
                      <button onClick={() => open("master")}>
                        Create master
                      </button>
                    </div>
                    {["branches", "warehouses", "bins", "costCentres", "ledgers", "taxProfiles", "customers", "contracts", "approvalPolicies", "automationRules"].map((c) => (
                      <div key={c}>
                        <h3>{c}</h3>
                        {state[c].map((r: Row) => (
                          <div className="list-row" key={r.id}>
                            <span>
                              {r.name} · {c === "approvalPolicies" ? (r.policyVersion
                                ? `${r.minAmount} ≤ total < ${r.maxAmount} ${state.settings.currency} · ${r.approvalStages} · ${r.active ? "Active" : "Inactive"} · ${r.allowAutomatic ? "Automatic permitted within limits" : "Human approval required"}`
                                : "Description only — edit to configure an approval range") : (r.type || r.address)}
                            </span>
                            <button
                              onClick={() =>
                                open("master", { ...r, collection: c })
                              }
                            >
                              Edit
                            </button>
                          </div>
                        ))}
                      </div>
                    ))}
                  </section>
                  <section className="panel">
                    <h2>Staff and supplier accounts</h2>
                    <p>
                      Create named accounts and share initial credentials
                      through your company’s secure channel.
                    </p>
                    {users.map((u) => (
                      <div className="list-row" key={u.id}>
                        <span>
                          {u.name} · {u.email} · {u.role}
                        </span>
                        <button
                          disabled={u.id === actor.id || !u.active || busy}
                          onClick={() =>
                            task(async () => {
                              await api("/users/" + u.id + "/disable", {});
                              setUsers(await api("/users"));
                            })
                          }
                        >
                          {u.active ? "Disable" : "Disabled"}
                        </button>
                      </div>
                    ))}
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        const form = e.currentTarget;
                        const data = Object.fromEntries(new FormData(form));
                        task(async () => {
                          await api("/users", {
                            ...data,
                            supplier_id: data.supplier_id || null,
                          });
                          form.reset();
                          setUsers(await api("/users"));
                        });
                      }}
                    >
                      <div className="grid">
                        <label>
                          Name
                          <input name="name" required />
                        </label>
                        <label>
                          Email
                          <input name="email" type="email" required />
                        </label>
                        <label>
                          Initial password
                          <input
                            name="password"
                            type="password"
                            minLength={12}
                            required
                            autoComplete="new-password"
                          />
                        </label>
                        <label>
                          Role
                          <select name="role">
                            {[
                              "buyer",
                              "requester",
                              "approver",
                              "stores",
                              "quality",
                              "production",
                              "sales",
                              "finance",
                              "viewer",
                              "admin",
                              "supplier",
                            ].map((r) => (
                              <option key={r}>{r}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Supplier assignment
                          <select name="supplier_id">
                            <option value="">Staff account</option>
                            {state.suppliers.map((s: Row) => (
                              <option value={s.id} key={s.id}>
                                {s.name}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                      <button disabled={busy}>Create account</button>
                    </form>
                  </section>
                  <DataTools
                    revision={revision}
                    company={state.settings.company}
                    task={task}
                  />
                </>
              )}
            </>
          )}
        </main>
        <footer className="footer">
          <span>
            <CheckCircle2 size={13} /> Server-backed workspace · revision{" "}
            {revision}
          </span>
          <span>
            F9 Purchase order · Ctrl F9 Invoice · Ctrl S Save · F5 Refresh
          </span>
        </footer>
      </div>
      {modal && (
        <div className="overlay">
          <section
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label={labels[modal.action] || modal.action}
          >
            <header>
              <div>
                <span className="eyebrow">VOUCHER ENTRY</span>
                <h2>{labels[modal.action] || modal.action}</h2>
              </div>
              <button aria-label="Close" onClick={() => setModal(null)}>
                <X />
              </button>
            </header>
            <form
              id="voucher-form"
              onSubmit={async (e) => {
                e.preventDefault();
                await command(modal.action, values);
              }}
            >
              {modal.action === "queueSupplierMessage" && <section className="panel">
                <button type="button" disabled={busy} onClick={() => task(async () => {
                  const preview = await api("/supplier-message-preview", {source: values.source, purpose: values.purpose, channel: values.channel});
                  setValues(v => ({...v, messagePreview: `${preview.recipient}\n${preview.subject}\n\n${preview.body}`}));
                })}>Preview message</button>
                <pre style={{whiteSpace: "pre-wrap"}}>{values.messagePreview || "Preview the supplier, document and message before queueing."}</pre>
              </section>}
              {modal.action === "bankStatementImport" && <section className="panel">
                <p>Choose a saved mapping for your bank's headers, separator and date format. Standard files use YYYY-MM-DD; mapped files can also use DD/MM/YYYY or MM/DD/YYYY. Keep entries oldest first. Up to 500 rows / 1 MB. Money in increases the bank balance.</p>
                <label>Column mapping<select value={values.mappingId || ""} disabled={busy} onChange={e => setValues(v => ({...v, mappingId: e.target.value, previewHash: "", bankPreview: null}))}><option value="">Standard date/reference/money_in/money_out</option>{(state.settings.bankImportMappings || []).filter((m: Row) => m.active !== false).map((m: Row) => <option value={m.id} key={m.id}>{m.name}</option>)}</select></label>
                <label>Statement CSV / TSV<input type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" disabled={busy} onChange={e => {
                  const file = e.target.files?.[0];
                  setValues(v => ({...v, csv: "", previewHash: "", bankPreview: null}));
                  if (!file) return;
                  task(async () => {
                    if (file.size > 1000000) throw new Error("Choose a CSV no larger than 1 MB.");
                    const csv = await file.text();
                    setValues(v => ({...v, csv, previewHash: "", bankPreview: null}));
                  });
                }}/></label>
                <button type="button" disabled={busy || !values.csv} onClick={() => task(async () => {
                  const preview = await api("/bank-import-preview", {csv: values.csv, bankLedger: values.bankLedger, statementCurrency: values.statementCurrency, openingBalance: values.openingBalance === "" ? null : values.openingBalance ?? null, mappingId: values.mappingId || null});
                  setValues(v => ({...v, previewHash: preview.previewHash, bankPreview: preview}));
                })}>Validate and preview</button>
                {values.bankPreview && <div><p>{values.bankPreview.rowCount} rows · Money in {values.bankPreview.moneyIn} · Money out {values.bankPreview.moneyOut} · Closing balance {values.bankPreview.closingBalance ?? "not supplied"} {values.bankPreview.currency}</p><p>Changing the file or settings requires another preview. Import records statement lines only.</p>
                  <div style={{maxHeight: 240, overflow: "auto"}}><table><thead><tr><th>Date</th><th>Reference</th><th>Direction</th><th>Amount</th></tr></thead><tbody>{values.bankPreview.rows.map((r: Row) => <tr key={r.reference}><td>{r.date}</td><td>{r.reference}</td><td>{r.direction}</td><td>{r.amount}</td></tr>)}</tbody></table></div></div>}
              </section>}
              <div className="form-body grid">
                {forms[modal.action]?.filter(f => {
                  if (modal.action !== "master") return true;
                  const approvalFields = ["minAmount", "maxAmount", "approvalStages", "allowAutomatic", "approvalHours", "escalationRole"];
                  if (values.collection === "approvalPolicies") {
                    return ["collection", "name", "description", "active", ...approvalFields].includes(f.key);
                  }
                  return !approvalFields.includes(f.key);
                }).map(field)}
              </div>
              {message && (
                <p className="notice" role="alert">
                  {message}
                </p>
              )}
              <footer>
                {[
                  "order",
                  "editOrder",
                  "invoice",
                  "editInvoice",
                  "requisition",
                  "quote",
                  "supplier",
                  "item",
                ].includes(modal.action) && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      command("saveDraft", {
                        kind: modal.action,
                        record: values.id || "",
                        values,
                      })
                    }
                  >
                    Save draft
                  </button>
                )}
                <button type="button" onClick={() => setModal(null)}>
                  Cancel
                </button>
                <button className="primary" disabled={busy || (modal.action === "bankStatementImport" && !values.previewHash)}>
                  {busy ? "Saving…" : "Save voucher"}
                </button>
              </footer>
            </form>
          </section>
        </div>
      )}
      {detail && (
        <div className="overlay">
          <section
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Record details"
          >
            <header>
              <h2>{detail.name || detail.number || detail.id}</h2>
              <button aria-label="Close" onClick={() => setDetail(null)}>
                <X />
              </button>
            </header>
            <div className="form-body">
              <div className="detail-grid">
                {Object.entries(detail)
                  .filter(
                    ([k, v]) => !k.startsWith("_") && typeof v !== "object",
                  )
                  .map(([k, v]) => (
                    <div key={k}>
                      <small>{k}</small>
                      <span>{String(v)}</span>
                    </div>
                  ))}
              </div>
              {detail._collection === "productionOrders" && <section>
                <h3>Production cost and dependencies</h3>
                <p>Issued material cost: {money(detail.materialCost || 0)} · Allocated to output: {money(detail.allocatedMaterialCost || 0)} · Remaining material WIP: {money(Number(detail.materialCost || 0) - Number(detail.allocatedMaterialCost || 0))}</p>
                {detail.planningReference && <p>Material plan: {detail.planningReference}</p>}
                {detail.planningDependencies?.length > 0 && <p>Component production orders: {detail.planningDependencies.join(", ")}</p>}
                {detail.plannedOrders?.length > 0 && <p>All planned production orders: {detail.plannedOrders.join(", ")}</p>}
                {detail.purchaseRequests?.length > 0 && <p>Pending purchase requests: {detail.purchaseRequests.join(", ")}</p>}
                {(detail.outputs || []).map((o: Row) => <div key={o.movement}><p>{o.date} · Output {o.qty} · Material {money(o.materialCost)} · Conversion {money(o.conversionCost)} · {o.final ? "Final" : "Partial"}</p>
                  {(o.materialAllocations || []).map((a: Row) => <small key={a.movement}>{name("items",a.item)} · input {a.movement} · quantity {a.qty} · cost {money(a.cost)}<br /></small>)}
                </div>)}
              </section>}
              {detail.lines && (
                <table>
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>Qty</th>
                      <th>Price</th>
                      <th>Discount</th>
                      <th>Tax</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.lines.map((l: Row) => (
                      <tr key={l.item}>
                        <td>{name("items", l.item)}</td>
                        <td>{l.qty}</td>
                        <td>{money(l.price)}</td>
                        <td>{l.discount || 0}%</td>
                        <td>{l.taxRate ?? detail.tax ?? 0}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {detail._collection === "communications" && (
                <section>
                  <h3>Message preview</h3><pre style={{whiteSpace: "pre-wrap"}}>{detail.body}</pre>
                  <h3>Delivery history</h3>
                  {(detail.events || []).map((e: Row, i: number) => <p key={i}>{e.at} · {e.status} · {e.detail}</p>)}
                </section>
              )}
              {detail.entries && (
                <table>
                  <thead>
                    <tr>
                      <th>Account</th>
                      <th>Debit</th>
                      <th>Credit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.entries.map((e: Row, i: number) => (
                      <tr key={i}>
                        <td>{e.account}</td>
                        <td>{money(e.debit)}</td>
                        <td>{money(e.credit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {detail.approvalRoute && (
                <p>Required approval sequence: {detail.approvalRoute.stages.join(" → ")}
                  {detail.status === "Pending approval" && ` · Next stage: ${detail.approvalRoute.stages[detail.approvals?.length || 0]}`}
                </p>
              )}
              {detail.status === "Pending approval" && detail.approvalDueAt && <p>Approval due: {new Date(detail.approvalDueAt).toLocaleString()}</p>}
              {detail.status === "Pending approval" && detail.approvalEscalation && <p role="status">Overdue approval escalated to {detail.approvalEscalation.role}. Approval is still required.</p>}
              {detail.status === "Pending approval" && detail.approvalDelegate && <p>Assigned substitute: {detail.approvalDelegate.name} · Expires {new Date(detail.approvalDelegate.expiresAt).toLocaleString()}</p>}
              {detail.approvalEvents?.length > 0 && <section><h3>Approval routing history</h3>{detail.approvalEvents.map((event: Row, index: number) => <p key={index}>{event.kind} · stage {event.stage + 1} · {new Date(event.at).toLocaleString()} · {event.name || event.role || ""} {event.reason || ""}</p>)}</section>}
              {detail.approvals?.length > 0 && (
                <>
                  <h3>Approvals</h3>
                  {detail.approvals.map((a: Row, i: number) => (
                    <p key={i}>
                      {a.role} · {a.actor} · revision {a.revision}
                    </p>
                  ))}
                </>
              )}
              {[
                "orders",
                "requisitions",
                "quotes",
                "receipts",
                "invoices",
              ].includes(detail._collection) && (
                <>
                  <h3>Attachments</h3>
                  {state.attachments
                    .filter((a: Row) => a.target === detail.id)
                    .map((a: Row) => (
                      <p key={a.id}>
                        <button disabled={busy} onClick={() => task(() => downloadDocument(a.id, a.name))}>{a.name}</button>
                      </p>
                    ))}
                  <label>
                    Attach supporting document
                    <input
                      type="file"
                      accept="application/pdf,image/png,image/jpeg"
                      disabled={busy}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        const data = new FormData();
                        data.set("file", file);
                        data.set("target", detail.id);
                        data.set("collection", detail._collection);
                        data.set("revision", String(revision));
                        task(() => api("/documents", data));
                      }}
                    />
                  </label>
                </>
              )}
              {["orders", "requisitions", "receipts", "invoices"].includes(
                detail._collection,
              ) && (
                <>
                  <h3>Comments</h3>
                  {state.comments
                    .filter((c: Row) => c.target === detail.id)
                    .map((c: Row) => (
                      <p key={c.id}>{c.text}</p>
                    ))}
                  {can(actor, "comment") && (
                    <button
                      onClick={() =>
                        open("comment", {
                          id: detail.id,
                          collection: detail._collection,
                        })
                      }
                    >
                      Add comment
                    </button>
                  )}
                </>
              )}
            </div>
            <footer>
              {detail._collection === "orders" && (
                <button onClick={() => printOrder(detail, state)}>
                  Print purchase order
                </button>
              )}
              {actions(detail._collection, detail)}
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}

function addDays(day: string, days: number) {
  const d = new Date(day + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + Number(days));
  return d.toISOString().slice(0, 10);
}
function download(name: string, contents: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function downloadCSV(name: string, rows: Row[]) {
  const keys = [
    ...new Set(
      rows.flatMap((r) =>
        Object.keys(r).filter((k) => typeof r[k] !== "object"),
      ),
    ),
  ];
  const cell = (v: unknown) => {
    let str = String(v ?? "");
    if (/^[=+@\-\t\r]/.test(str)) str = "'" + str;
    return '"' + str.replaceAll('"', '""') + '"';
  };
  download(
    name + ".csv",
    [
      keys.map(cell).join(","),
      ...rows.map((r) => keys.map((k) => cell(r[k])).join(",")),
    ].join("\r\n"),
    "text/csv",
  );
}
function printOrder(order: Row, state: Row) {
  const w = window.open("", "_blank");
  if (!w) return;
  const escape = (value: unknown) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  w.document.write(
    "<!doctype html><html><head><title>Purchase order</title><style>body{font:14px Arial;padding:40px}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}</style></head><body><h1>" +
      escape(state.settings.company) +
      "</h1><h2>Purchase order " +
      escape(order.id) +
      "</h2><p>Supplier: " +
      escape(state.suppliers.find((v: Row) => v.id === order.supplier)?.name) +
      "</p><p>Delivery: " +
      escape(order.due) +
      " · " +
      escape(order.deliveryAddress) +
      "</p><table><tr><th>Item</th><th>Quantity</th><th>Price</th></tr>" +
      order.lines
        .map(
          (l: Row) =>
            "<tr><td>" +
            escape(state.items.find((i: Row) => i.id === l.item)?.name) +
            "</td><td>" +
            escape(l.qty) +
            "</td><td>" +
            escape(money(l.price)) +
            "</td></tr>",
        )
        .join("") +
      "</table><h3>Total: " +
      escape(money(total(order))) +
      "</h3><p>" +
      escape(order.paymentTerms) +
      "</p><p>" +
      escape(order.note) +
      "</p></body></html>",
  );
  w.document.close();
  w.focus();
  w.print();
}
function DataTools({
  revision,
  company,
  task,
}: {
  revision: number;
  company: string;
  task: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [pass, setPass] = useState(""),
    [backup, setBackup] = useState<Row | null>(null),
    [preview, setPreview] = useState<Row | null>(null),
    [confirmation, setConfirmation] = useState("");
  const [kind, setKind] = useState("supplier"),
    [csv, setCsv] = useState(""),
    [checked, setChecked] = useState(false);
  function parseCSV(input: string) {
    const rows: string[][] = [];
    let row: string[] = [],
      cell = "",
      quoted = false;
    for (let i = 0; i < input.length; i++) {
      const c = input[i];
      if (c === '"') {
        if (quoted && input[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = !quoted;
      } else if (c === "," && !quoted) {
        row.push(cell);
        cell = "";
      } else if ((c === "\n" || c === "\r") && !quoted) {
        if (c === "\r" && input[i + 1] === "\n") i++;
        row.push(cell);
        if (row.some(Boolean)) rows.push(row);
        row = [];
        cell = "";
      } else cell += c;
    }
    if (quoted) throw Error("Unclosed CSV quote.");
    row.push(cell);
    if (row.some(Boolean)) rows.push(row);
    const keys = rows.shift() || [];
    if (
      new Set(keys).size !== keys.length ||
      !keys.includes("name") ||
      keys.some((k) => ["__proto__", "constructor", "prototype"].includes(k))
    )
      throw Error("Use unique safe headers including name.");
    return rows.map((row) =>
      Object.fromEntries(keys.map((key, i) => [key.trim(), row[i] || ""])),
    );
  }
  return (
    <>
      <section className="panel">
        <h2>Master data import</h2>
        <select
          aria-label="Import type"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setChecked(false);
          }}
        >
          <option value="supplier">Suppliers</option>
          <option value="item">Items</option>
        </select>
        <button
          onClick={() =>
            download(
              "template.csv",
              kind === "supplier"
                ? "name,email,terms,creditDays,leadDays\n"
                : "name,sku,unit,supplier,price,stock,reorder,target,inspectionRequired\n",
              "text/csv",
            )
          }
        >
          Download CSV template
        </button>
        <label>
          CSV file
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f && f.size <= 1_000_000) {
                setCsv(await f.text());
                setChecked(false);
              }
            }}
          />
        </label>
        <button
          disabled={!csv}
          onClick={() =>
            task(async () => {
              await api("/imports", {
                action: kind,
                data: { rows: parseCSV(csv), preview: true },
                revision,
                requestId: crypto.randomUUID(),
              });
              setChecked(true);
            })
          }
        >
          Validate import
        </button>
        <button
          disabled={!checked}
          onClick={() =>
            task(async () => {
              await api("/imports", {
                action: kind,
                data: { rows: parseCSV(csv), preview: false },
                revision,
                requestId: crypto.randomUUID(),
              });
              setChecked(false);
              setCsv("");
            })
          }
        >
          Import validated rows
        </button>
        <p className="hint">
          Imports are atomic. New suppliers still require qualification.
        </p>
      </section>
      <section className="panel">
        <h2>Encrypted backup & recovery</h2>
        <p>
          Keep backups in independent storage. The passphrase cannot be
          recovered. Portable exports support up to 10 MB of attachments.
        </p>
        <label>
          Backup passphrase
          <input
            type="password"
            minLength={12}
            value={pass}
            onChange={(e) => {
              setPass(e.target.value);
              setPreview(null);
            }}
            autoComplete="off"
          />
        </label>
        <button
          disabled={pass.length < 12}
          onClick={() =>
            task(async () => {
              const result = await api("/backup/export", { passphrase: pass });
              download(
                "lubriflow-" + localDate() + ".encrypted.json",
                JSON.stringify(result),
              );
              setPass("");
            })
          }
        >
          Download encrypted backup
        </button>
        <label>
          Restore file
          <input
            type="file"
            accept=".json"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              setPreview(null);
              if (file && file.size <= 20_000_000) {
                try {
                  setBackup(JSON.parse(await file.text()));
                } catch {
                  setBackup(null);
                }
              }
            }}
          />
        </label>
        <button
          disabled={!backup || pass.length < 12}
          onClick={() =>
            task(async () =>
              setPreview(
                await api("/backup/restore", {
                  passphrase: pass,
                  envelope: backup,
                  revision,
                  preview: true,
                }),
              ),
            )
          }
        >
          Verify backup
        </button>
        {preview && (
          <>
            <p>
              Verified: {preview.orders} orders · {preview.invoices} invoices ·{" "}
              {preview.documents} documents. Restoration replaces current
              business records.
            </p>
            <label>
              Type “{company}” to confirm
              <input
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
              />
            </label>
            <button
              className="danger-button"
              disabled={confirmation !== company}
              onClick={() =>
                task(async () => {
                  await api("/backup/restore", {
                    passphrase: pass,
                    envelope: backup,
                    revision,
                    preview: false,
                    company: confirmation,
                  });
                  setPreview(null);
                  setBackup(null);
                  setPass("");
                })
              }
            >
              Restore verified backup
            </button>
          </>
        )}
      </section>
    </>
  );
}
