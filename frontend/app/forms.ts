export type Row = Record<string, any>;
export type Field = {
  key: string;
  label: string;
  type?: string;
  source?: string;
  options?: string[];
  required?: boolean;
};
const f = (
  key: string,
  label: string,
  type = "text",
  source?: string,
): Field => ({ key, label, type, source });
const date = f("date", "Voucher date", "date");
const reason = f("reason", "Reason / narration");
const lines = f("lines", "Item lines", "lines");
const supplier = f("supplier", "Supplier", "select", "suppliers");
const po = f("po", "Purchase order", "select", "orders");
const item = f("item", "Item", "select", "items");
const locationFields = [f("bin", "Source / stock bin", "select", "bins"), f("lot", "Lot / batch"), f("serial", "Serial number")];
const invoice = f("invoice", "Purchase invoice", "select", "invoices");
const customer = f("customer", "Customer", "select", "customers");
const salesOrder = f("order", "Sales order", "select", "salesOrders");
const stockFields = [
  f("stock", "Opening stock", "number"),
  f("reorder", "Reorder point", "number"),
  f("target", "Target stock", "number"),
  f("packSize", "Pack multiple", "number"),
  f("minOrder", "Minimum order", "number"),
];
const supplierFields = [
  f("name", "Supplier name"),
  f("email", "Email", "email"),
  f("contact", "Contact person"),
  f("phone", "Phone"),
  f("taxId", "Tax registration number"),
  f("address", "Address", "textarea"),
  f("country", "Country"),
  f("terms", "Payment terms"),
  f("creditDays", "Credit days", "number"),
  f("leadDays", "Lead days", "number"),
];
const itemFields = [
  f("name", "Item name"),
  f("sku", "SKU"),
  f("unit", "Unit"),
  f("category", "Category"),
  f("specification", "Specification", "textarea"),
  f("grade", "Variant / grade"),
  supplier,
  f("price", "Default price", "number"),
  f("taxRate", "Tax %", "number"),
  ...stockFields,
  f("leadDays", "Lead days", "number"),
  f("inspectionRequired", "Inspection required", "checkbox"),
];
const currencyFields = [f("currency", "Transaction currency (blank = company currency)"), f("rate", "Exchange rate to base currency", "number")];
const orderFields = [
  ...currencyFields,
  supplier,
  date,
  f("due", "Expected delivery", "date"),
  f("warehouse", "Warehouse", "select", "warehouses"),
  f("costCentre", "Cost centre", "select", "costCentres"),
  f("project", "Project", "select", "projects"),
  f("purchaseLedger", "Purchase ledger", "select", "ledgers"),
  lines,
  f("tax", "Default tax %", "number"),
  f("freight", "Freight", "number"),
  f("paymentDays", "Payment days", "number"),
  f("paymentTerms", "Payment terms"),
  f("billingAddress", "Billing address", "textarea"),
  f("deliveryAddress", "Delivery address", "textarea"),
  f("reference", "Reference"),
  f("contact", "Contact"),
  f("dispatchThrough", "Dispatch through"),
  f("destination", "Destination"),
  f("deliveryTerms", "Delivery terms"),
  f("note", "Notes", "textarea"),
];
const invoiceFields = [
  f("rate", "Invoice exchange rate to base currency", "number"),
  po,
  f("number", "Supplier invoice reference"),
  date,
  f("supplierDate", "Supplier invoice date", "date"),
  f("due", "Payment due date", "date"),
  lines,
  f("tax", "Default tax %", "number"),
  f("freight", "Freight", "number"),
  f("amount", "Declared invoice total", "number"),
  f("note", "Notes", "textarea"),
];
export const forms: Record<string, Field[]> = {
  stockDisposition: [f("position", "Stock position", "select", "stockPositions"), {...f("status", "Quality disposition", "options"), options: ["Quarantined", "Available"]}, reason],
  confirmOpeningCost: [f("position", "Opening position", "select", "stockPositions"), f("value", "Verified opening stock value", "number"), date, reason],
  itemTracking: [item, {...f("tracking", "Tracking mode", "options"), options: ["none", "lot", "serial"]}, f("barcode", "Barcode")],
  stockCount: [f("position", "Stock position", "select", "stockPositions"), f("counted", "Observed quantity", "number"), date, reason],
  reserveStock: [f("position", "Stock position", "select", "stockPositions"), {...f("sourceKind", "Source order type", "options"), options: ["salesOrders", "productionOrders"]}, f("source", "Sales / production order reference"), f("qty", "Reserve quantity", "number")],
  releaseReservation: [reason],
  relocateStock: [item, f("fromWarehouse", "Source warehouse", "select", "warehouses"), ...locationFields, f("toWarehouse", "Destination warehouse", "select", "warehouses"), f("toBin", "Destination bin", "select", "bins"), f("qty", "Quantity", "number"), date, reason],
  landedCost: [f("receipt", "Accepted receipt", "select", "receipts"), f("reference", "Freight / duty invoice reference"), f("amount", "Additional cost", "number"), f("expenseAccount", "Posted expense account to capitalise (perpetual mode)"), f("expenseJournal", "Source expense journal ID (perpetual mode)"), date],
  salesQuote: [customer, date, ...currencyFields, f("due", "Expected delivery", "date"), f("validUntil", "Valid until", "date"), f("warehouse", "Warehouse", "select", "warehouses"), lines, f("tax", "Tax %", "number"), f("note", "Notes", "textarea")],
  closeSalesOrder: [reason],
  salesReturn: [f("delivery", "Delivery", "select", "deliveries"), item, f("position", "Original delivery position", "select", "stockPositions"), f("qty", "Return quantity", "number"), f("bin", "Inspected return bin", "select", "bins"), date, reason],
  customerCredit: [f("invoice", "Customer invoice", "select", "salesInvoices"), f("return", "Customer return", "select", "salesReturns"), f("qty", "Credit quantity", "number"), date, reason],
  bom: [f("name", "BOM name / version"), f("output", "Finished item", "select", "items"), f("outputQty", "Base output quantity", "number"), lines],
  productionOrder: [f("bom", "BOM version", "select", "boms"), f("qty", "Planned output quantity", "number"), f("warehouse", "Production warehouse", "select", "warehouses"), date, f("note", "Notes")],
  consumeProduction: [date, lines],
  finishProduction: [date, f("partial", "Partial output — keep order open (consume only proportional materials)", "checkbox"), f("outputQty", "Actual output quantity", "number"), f("conversionCost", "Labour / overhead cost for this output", "number"), f("bin", "Output bin", "select", "bins"), f("lot", "Output lot"), f("serial", "Output serial"), f("expiry", "Output expiry", "date"), reason],
  cancelProduction: [reason],
  createRFQ: [supplier, f("due", "Quotation response deadline", "date"), lines, f("note", "Requirements / specifications", "textarea")],
  closeRFQ: [reason],
  supplierMessaging: [supplier, {...f("channel", "Channel", "options"), options: ["email", "whatsapp"]}, f("address", "Email address or WhatsApp number (+country code)"), f("consent", "Supplier authorised this channel", "checkbox"), f("evidence", "Consent / revocation reference", "textarea")],
  messagingPolicy: [f("enabled", "Automatically queue supplier messages", "checkbox"), {...f("channel", "Automatic channel", "options"), options: ["email", "whatsapp"]}, f("intervalDays", "Minimum days between reminders", "number"), f("maxReminders", "Maximum reminders per purpose", "number")],
  queueSupplierMessage: [{...f("purpose", "Message purpose", "options"), options: ["rfq", "po", "rfqReminder", "ackReminder", "deliveryChase"]}, f("source", "RFQ or PO reference"), {...f("channel", "Channel", "options"), options: ["email", "whatsapp"]}],
  cancelSupplierMessage: [reason],
  supplier: supplierFields,
  editSupplier: supplierFields,
  item: itemFields,
  editItem: itemFields,
  requisition: [
    date,
    f("department", "Department"),
    lines,
    f("note", "Notes", "textarea"),
  ],
  quote: [
    supplier,
    ...currencyFields,
    f("tax", "Default tax %", "number"), f("freight", "Quoted freight", "number"), f("paymentDays", "Payment days", "number"),
    f("rfq", "Reply to RFQ (optional)", "select", "rfqs"),
    date,
    f("valid", "Valid until", "date"),
    f("leadDays", "Lead days", "number"),
    lines,
    f("note", "Notes", "textarea"),
  ],
  order: orderFields,
  approveSupplier: [f("approved", "Qualified", "checkbox"), f("qualificationUntil", "Qualification valid through (blank = no expiry)", "date"), reason],
  editOrder: [...orderFields, reason],
  invoice: invoiceFields,
  editInvoice: invoiceFields,
  receipt: [
    po,
    date,
    lines,
    f("batch", "Batch / lot"),
    f("certificate", "Inspection or compliance certificate"),
    f("deliveryNote", "Delivery note"),
    f("vehicle", "Vehicle"),
    f("transporter", "Transporter"),
    f("manufactured", "Manufacture date", "date"),
    f("expiry", "Expiry date", "date"),
  ],
  return: [
    f("receipt", "Goods receipt", "select", "receipts"),
    date,
    lines,
    reason,
  ],
  credit: [
    invoice,
    f("number", "Supplier credit reference"),
    date,
    lines,
    reason,
  ],
  pay: [
    f("amount", "Amount paid", "number"),
    date,
    f("bankLedger", "Bank / cash ledger", "select", "ledgers"),
    f("reference", "External payment reference"),
    f("method", "Method"),
    f("note", "Notes"),
  ],
  reversePayment: [date, reason],
  preclose: [lines, reason],
  accept: [reason],
  rejectReceipt: [reason],
  reject: [reason],
  delegateApproval: [f("userId", "Substitute approver", "select", "approvalUsers"), f("validHours", "Assignment duration in hours (1 to 720)", "number"), reason],
  revokeApprovalDelegation: [reason],
  rejectPR: [reason],
  cancel: [reason],
  voidInvoice: [reason],
  stockIssue: [
    item,
    date,
    ...locationFields,
    f("warehouse", "Warehouse", "select", "warehouses"),
    f("qty", "Quantity", "number"),
    reason,
  ],
  stockTransfer: [
    item,
    date,
    ...locationFields,
    f("toBin", "Destination bin", "select", "bins"),
    f("fromWarehouse", "From warehouse", "select", "warehouses"),
    f("toWarehouse", "To warehouse", "select", "warehouses"),
    f("qty", "Quantity", "number"),
    reason,
  ],
  priceAgreement: [
    supplier,
    item,
    f("price", "Unit price", "number"),
    f("discount", "Discount %", "number"),
    f("taxRate", "Tax %", "number"),
    f("validFrom", "Valid from", "date"),
    f("validUntil", "Valid until", "date"),
    f("reference", "Agreement reference"),
  ],
  master: [
    {
      ...f("collection", "Master collection", "options"),
      options: ["warehouses", "costCentres", "ledgers", "branches", "bins", "taxProfiles", "customers", "contracts", "approvalPolicies", "automationRules"],
    },
    f("name", "Name"),
    f("address", "Address"),
    f("warehouse", "Warehouse", "select", "warehouses"),
    f("rate", "Tax rate %", "number"),
    f("email", "Email", "email"),
    f("phone", "Phone"),
    f("taxId", "Tax registration number"),
    f("creditDays", "Credit days", "number"),
    f("creditLimit", "Credit limit", "number"),
    f("description", "Description", "textarea"),
    f("minAmount", "Approval policy lower limit in base currency (inclusive)", "number"),
    f("maxAmount", "Approval policy upper limit in base currency (exclusive)", "number"),
    f("approvalStages", "Approval policy stages in order: approver, finance, admin"),
    f("allowAutomatic", "Approval policy permits automatic approval within company limits", "checkbox"),
    f("approvalHours", "Hours per approval stage before escalation (0 disables)", "number"),
    {...f("escalationRole", "Escalation queue owner", "options"), options: ["admin", "finance"]},
    {
      ...f("type", "Ledger type", "options"),
      options: ["purchase", "bank", "cash"],
    },
    f("active", "Active", "checkbox"),
  ],
  account: [
    f("name", "Account name"),
    {
      ...f("type", "Classification", "options"),
      options: ["asset", "liability", "equity", "revenue", "expense"],
    },
  ],
  journal: [
    date,
    reason,
    f("reference", "Reference"),
    f("entries", "Journal lines", "journal"),
  ],
  reverseJournal: [date, reason],
  comment: [f("text", "Comment", "textarea")],
  linkSubmission: [invoice],
  rejectSubmission: [reason],
  salesOrder: [customer, date, ...currencyFields, f("costCentre", "Cost centre", "select", "costCentres"), f("project", "Project", "select", "projects"), f("due", "Promised date", "date"), f("warehouse", "Warehouse", "select", "warehouses"), lines, f("tax", "Default tax %", "number"), f("note", "Notes", "textarea")],
  deliverSale: [salesOrder, date, lines],
  salesInvoice: [salesOrder, f("rate", "Invoice exchange rate to base currency", "number"), f("number", "Customer invoice reference"), date, f("due", "Payment due date", "date"), lines, f("tax", "Default tax %", "number")],
  customerPayment: [f("invoice", "Customer invoice", "select", "salesInvoices"), f("amount", "Amount received", "number"), date, f("bankLedger", "Bank / cash ledger", "select", "ledgers"), f("reference", "Receipt reference")],
  bankStatement: [f("bankLedger", "Bank / cash ledger", "select", "ledgers"), date, f("reference", "Bank statement reference"), f("amount", "Amount", "number"), {...f("direction", "Direction", "options"), options: ["debit", "credit"]}, f("description", "Description")],
  bankStatementImport: [f("bankLedger", "Bank / cash ledger", "select", "ledgers"), f("statementCurrency", "Statement currency (for example AED)"), f("openingBalance", "Opening balance (required if CSV has balances)", "number")],
  reconcileBank: [f("statement", "Statement line", "select", "bankStatements"), {...f("collection", "Transaction type", "options"), options: ["payments", "customerPayments", "partyFunds", "fundRefunds"]}, f("transaction", "Transaction ID")],
  asset: [f("name", "Asset name"), date, f("availableDate", "Available-for-use date (defaults to acquisition)", "date"), f("cost", "Capitalised cost", "number"), f("residual", "Residual value", "number"), f("lifeMonths", "Useful life in months", "number"), f("assetAccount", "Asset account ID", "text"), f("creditAccount", "Funding account ID", "text")],
  depreciate: [f("periodEnd", "Period end", "date")],
  exchangeRate: [f("fromCurrency", "Source currency (ISO)"), f("toCurrency", "Target currency (ISO)"), date, f("rate", "Base rate", "number"), f("source", "Rate source")],
  taxWorkpaper: [f("start", "Period start", "date"), f("end", "Period end", "date")],
  closePeriod: [f("through", "Lock through", "date")],
  closeYear: [f("end", "Financial year end", "date")],
};
export const labels: Record<string, string> = {
  delegateApproval: "Assign approval substitute",
  revokeApprovalDelegation: "Revoke approval substitute",
  stockDisposition: "Quarantine / release stock", confirmOpeningCost: "Confirm opening inventory cost",
  itemTracking: "Barcode and tracking setup", stockCount: "Stock count", reserveStock: "Reserve stock", releaseReservation: "Release reservation",
  relocateStock: "Warehouse / bin movement", landedCost: "Allocate landed cost", salesQuote: "Customer quotation", closeSalesOrder: "Close sales order",
  salesReturn: "Inspected customer return", customerCredit: "Customer credit note", bom: "Bill of materials", productionOrder: "Production order",
  consumeProduction: "Consume production materials", finishProduction: "Complete production", cancelProduction: "Cancel production",
  createRFQ: "Request for quotation",
  closeRFQ: "Close RFQ",
  supplierMessaging: "Supplier messaging permission",
  messagingPolicy: "Supplier message automation",
  queueSupplierMessage: "Queue supplier message",
  cancelSupplierMessage: "Cancel unsent message",
  supplier: "Supplier",
  item: "Item",
  requisition: "Purchase requisition",
  quote: "Supplier quotation",
  approveSupplier: "Supplier qualification",
  order: "Purchase order",
  invoice: "Purchase invoice",
  receipt: "Goods receipt",
  return: "Supplier return",
  credit: "Supplier credit",
  pay: "Record external payment",
  master: "Master record",
  priceAgreement: "Price agreement",
  journal: "Manual journal",
  account: "Account",
  stockIssue: "Stock issue",
  stockTransfer: "Warehouse transfer",
  reversePayment: "Reverse payment",
  preclose: "Preclose order",
  linkSubmission: "Link reviewed voucher",
  rejectSubmission: "Reject submission",
  salesOrder: "Sales order",
  deliverSale: "Customer delivery",
  salesInvoice: "Sales invoice",
  customerPayment: "Record customer receipt",
  bankStatement: "Bank statement line",
  bankStatementImport: "Import bank statement",
  reconcileBank: "Reconcile bank transaction",
  asset: "Capitalise asset",
  depreciate: "Run depreciation",
  exchangeRate: "Exchange rate",
  taxWorkpaper: "Tax workpaper",
  closePeriod: "Close accounting period",
  closeYear: "Close financial year",
};
export const pages: Record<
  string,
  { title: string; sub: string; collection?: string; create?: string }
> = {
  procurementInsights: {title: "Purchasing insights", sub: "Comparable quotations, supplier qualification and explained demand planning."},
  stockPositions: {title: "Stock positions & valuation", sub: "Warehouse, bin, lot and serial availability with recorded costs.", collection: "stockPositions", create: "relocateStock"},
  stockCounts: {title: "Stock counts", sub: "Count, review and post stock variances.", collection: "stockCounts", create: "stockCount"},
  reservations: {title: "Stock reservations", sub: "Protect stock committed to customer orders.", collection: "reservations", create: "reserveStock"},
  landedCosts: {title: "Landed costs", sub: "Allocate freight and duties before stock is issued.", collection: "landedCosts", create: "landedCost"},
  salesQuotes: {title: "Customer quotations", sub: "Offer prices and convert accepted quotations to orders.", collection: "salesQuotes", create: "salesQuote"},
  salesReturns: {title: "Customer returns", sub: "Return inspected stock to its original lot and cost.", collection: "salesReturns", create: "salesReturn"},
  customerCredits: {title: "Customer credit notes", sub: "Credit returned quantities against unpaid receivables.", collection: "customerCredits", create: "customerCredit"},
  boms: {title: "Bills of materials", sub: "Versioned component requirements for configurable manufacturing.", collection: "boms", create: "bom"},
  productionOrders: {title: "Production orders", sub: "Release, consume, complete and trace manufacturing work.", collection: "productionOrders", create: "productionOrder"},
  rfqs: {title: "Requests for quotation", sub: "Request supplier offers and track responses.", collection: "rfqs", create: "createRFQ"},
  communications: {title: "Supplier messages", sub: "Email and WhatsApp delivery queue, reminders and message history.", collection: "communications", create: "queueSupplierMessage"},
  overview: {
    title: "Workspace overview",
    sub: "Purchasing, stock and financial work in one place.",
  },
  requisitions: {
    title: "Purchase requisitions",
    sub: "Record demand and route it for approval.",
    collection: "requisitions",
    create: "requisition",
  },
  quotes: {
    title: "Supplier quotations",
    sub: "Review offers and award valid quotations.",
    collection: "quotes",
    create: "quote",
  },
  orders: {
    title: "Purchase orders",
    sub: "Prepare, approve and track supplier commitments.",
    collection: "orders",
    create: "order",
  },
  receipts: {
    title: "Goods receipts",
    sub: "Receive deliveries and release inspected material.",
    collection: "receipts",
    create: "receipt",
  },
  invoices: {
    title: "Purchase invoices",
    sub: "Match bills to orders and accepted receipts.",
    collection: "invoices",
    create: "invoice",
  },
  returns: {
    title: "Supplier returns",
    sub: "Track physical goods returned to suppliers.",
    collection: "returns",
    create: "return",
  },
  credits: {
    title: "Supplier credits",
    sub: "Adjust unpaid posted bills with traceable credit notes.",
    collection: "credits",
    create: "credit",
  },
  payments: {
    title: "Payment register",
    sub: "Record external payments and approved reversals.",
    collection: "payments",
  },
  salesOrders: { title: "Sales orders", sub: "Customer demand, pricing and fulfilment commitments.", collection: "salesOrders", create: "salesOrder" },
  deliveries: { title: "Customer deliveries", sub: "Issue stock against approved customer orders.", collection: "deliveries", create: "deliverSale" },
  salesInvoices: { title: "Sales invoices", sub: "Post customer invoices from delivered quantities.", collection: "salesInvoices", create: "salesInvoice" },
  customerPayments: { title: "Customer receipts", sub: "Record and reconcile funds received.", collection: "customerPayments", create: "customerPayment" },
  bankStatements: { title: "Bank reconciliation", sub: "Capture statement lines and match recorded cash movements.", collection: "bankStatements", create: "bankStatement" },
  assets: { title: "Fixed assets", sub: "Capitalise assets and run controlled depreciation.", collection: "assets", create: "asset" },
  items: {
    title: "Inventory",
    sub: "Item specifications, warehouse balances and replenishment.",
    collection: "items",
    create: "item",
  },
  suppliers: {
    title: "Suppliers",
    sub: "Commercial details and supplier qualification.",
    collection: "suppliers",
    create: "supplier",
  },
  prices: {
    title: "Price agreements",
    sub: "Supplier rates with controlled validity periods.",
    collection: "prices",
    create: "priceAgreement",
  },
  books: {
    title: "Financial books",
    sub: "Journals, trial balance and financial statements.",
  },
  portalSubmissions: {
    title: "Supplier collaboration",
    sub: "Review submitted supplier invoice references.",
    collection: "portalSubmissions",
  },
  automation: {
    title: "Automation centre",
    sub: "Policy-controlled workflows with persistent run history.",
  },
  documents: {
    title: "Documents & capture",
    sub: "Supporting documents and invoice extraction.",
  },
  drafts: {
    title: "Saved drafts",
    sub: "Resume your unfinished voucher entries.",
    collection: "drafts",
  },
  audit: {
    title: "Audit trail",
    sub: "Recorded actors, commands and business changes.",
    collection: "audit",
  },
  settings: {
    title: "Company & controls",
    sub: "Company details, authority limits and system administration.",
  },
};
export function total(r: Row) {
  return (r.lines || []).reduce(
    (sum: number, l: Row) => {
      const net =
        Math.round(
          Number(l.qty || 0) *
            Number(l.price || 0) *
            (1 - Number(l.discount || 0) / 100) *
            100,
        ) / 100;
      return (
        sum + net + Math.round(net * Number(l.taxRate ?? r.tax ?? 0)) / 100
      );
    },
    Number(r.freight || 0),
  );
}
export function money(n: any) {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(Number(n || 0));
}
export function localDate() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "UTC" }).format(
    new Date(),
  );
}
