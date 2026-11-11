"use client";
import {useEffect, useState} from "react";
import {Row, money} from "./forms";

export default function ProcurementDashboard({state, actor, revision, busy, api, command}: {
  state: Row; actor: Row; revision: number; busy: boolean;
  api: (path: string) => Promise<Row>;
  command: (action: string, data: Row) => Promise<unknown>;
}) {
  const [report, setReport] = useState<Row | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    setReport(null); setError("");
    api("/procurement-insights").then(r => {if (current) setReport(r);})
      .catch(e => {if (current) setError(e.message);});
    return () => {current = false;};
  }, [revision, api]);
  const name = (collection: string, id: string) => state[collection].find((r: Row) => r.id === id)?.name || id;
  const buyer = ["admin", "buyer"].includes(actor.role);
  if (error) return <p role="alert">{error}</p>;
  if (!report) return <p role="status">Loading purchasing insights…</p>;
  return <>
    <section className="panel"><h2>Replenishment recommendations</h2>
      <p>{report.period.start} to {report.period.end}. {report.demandBasis}</p>
      <p>Trailing averages are planning estimates. Review seasonal demand and delivery dates. New requests remain subject to normal approval.</p>
      {actor.role === "admin" && <label>Automatic replenishment method<select disabled={busy} value={state.settings.reorderMethod || "threshold"}
        onChange={e => command("settings", {reorderMethod: e.target.value})}>
        <option value="threshold">Configured reorder point</option><option value="forecast">Demand average with lead-time buffers</option>
      </select><small>Runs only when automatic mode and autoReorder are enabled. Manual requests are always available.</small></label>}
      {!report.forecastPurchaseRecommendations.length && <p>No replenishment recommendation from the available demand history.</p>}
      <div className="table-wrap"><table><thead><tr><th>Item</th><th>Daily demand</th><th>Available / incoming</th><th>Suggested quantity</th><th>Review</th></tr></thead><tbody>
        {report.forecastPurchaseRecommendations.map((r: Row) => <tr key={r.item}><td>{name("items", r.item)}</td><td>{Number(r.averageDailyDemand).toFixed(3)}<small>{r.observedDemand} units / {r.lookbackDays} days</small></td><td>{r.available} / {r.incoming}<small>{r.reserved} reserved</small></td><td>{r.suggestedQty}<small>{r.daysOfCover} days cover</small></td><td>{r.blockedReason || (buyer ? <button disabled={busy} onClick={() => command("forecastRequisition", {item:r.item})}>Create approval request</button> : "Buyer review required")}</td></tr>)}
      </tbody></table></div>
    </section>
    <section className="panel"><h2>Like-for-like quotation baskets</h2><p>Only identical items and quantities are grouped. Totals include quoted tax and freight, converted at each quotation's recorded rate into {report.baseCurrency}. Different tax recovery or delivery terms still need buyer review. Awarding creates a draft PO.</p>
      {!report.basketComparisons.length && <p>No current quotations to compare.</p>}
      {report.basketComparisons.map((basket: Row, index: number) => <div key={index}><h3>{basket.lines.map((l: Row) => `${name("items", l.item)} × ${l.qty}`).join(" · ")}</h3><div className="table-wrap"><table><thead><tr><th>Supplier / quote</th><th>Quoted total</th><th>Base total</th><th>Lead / payment days</th><th>Decision</th></tr></thead><tbody>
        {basket.offers.map((o: Row) => <tr key={o.quote}><td>{name("suppliers", o.supplier)}<small>{o.quote}</small></td><td>{money(o.total)} {o.currency}</td><td>{money(o.baseTotal)} {report.baseCurrency}</td><td>{o.leadDays} / {o.paymentDays}</td><td>{!o.qualified ? "Qualification required" : buyer ? <button disabled={busy} onClick={() => command("award", {id:o.quote})}>Create draft PO from quote</button> : "Buyer review required"}</td></tr>)}
      </tbody></table></div></div>)}
    </section>
    <section className="panel"><h2>Supplier performance and qualification</h2><p>Acceptance is based on completed inspections; pending inspections are shown separately. On-time percentage covers accepted receipts, not an order fill-rate score.</p>
      <div className="table-wrap"><table><thead><tr><th>Supplier</th><th>Qualification</th><th>Evaluated / pending receipts</th><th>Acceptance</th><th>On time</th></tr></thead><tbody>
        {report.supplierScorecards.map((r: Row) => <tr key={r.supplier}><td>{name("suppliers", r.supplier)}</td><td>{r.qualified ? "Qualified" : "Expired / unqualified"}<small>{r.qualificationUntil || "No expiry recorded"}</small></td><td>{r.evaluatedReceipts} / {r.pendingInspection}</td><td>{r.acceptanceRate === null ? "No evidence" : `${r.acceptanceRate}%`}</td><td>{r.onTimeRate === null ? "No evidence" : `${r.onTimeRate}%`}</td></tr>)}
      </tbody></table></div>
    </section>
  </>;
}
