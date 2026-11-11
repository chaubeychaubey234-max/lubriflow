"use client";
import {useEffect, useState} from "react";
import {Row} from "./forms";

export default function MaterialPlanner({state, revision, busy, api, command}: {
  state: Row; revision: number; busy: boolean;
  api: (path: string, body?: unknown) => Promise<Row>;
  command: (action: string, data: Row) => Promise<unknown>;
}) {
  const [inputs, setInputs] = useState<Row>({bom:"", qty:1, warehouse:"WH-MAIN", reference:"", bomSelections:{}, createPurchaseRequests:false});
  const [preview, setPreview] = useState<Row | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {setPreview(null);}, [revision]);
  const update = (key: string, value: unknown) => {setInputs(v => ({...v,[key]:value})); setPreview(null); setMessage("");};
  const name = (id: string) => state.items.find((i: Row) => i.id === id)?.name || id;
  const active = state.boms.filter((b: Row) => b.status === "Active");
  const outputs = [...new Set<string>(active.map((b: Row) => b.output))];
  const root = active.find((b: Row) => b.id === inputs.bom);
  const disabled = busy || pending;
  return <section className="panel"><h2>Plan subassemblies and materials</h2>
    <p>Choose the finished product BOM and quantity to manufacture. Preview expands all selected BOM levels and deducts usable, unreserved stock in one warehouse. It does not count future deliveries or unfinished production.</p>
    <form onSubmit={async e => {
      e.preventDefault(); setPending(true); setPreview(null); setMessage("");
      try {setPreview(await api("/material-plan-preview", {...inputs, qty:Number(inputs.qty)}));}
      catch (error) {setMessage((error as Error).message);} finally {setPending(false);}
    }}><fieldset disabled={disabled} style={{border:0,padding:0}}><div className="grid">
      <label>Planning reference<input required maxLength={100} value={inputs.reference} onChange={e => update("reference",e.target.value)} /></label>
      <label>Finished product BOM<select required value={inputs.bom} onChange={e => update("bom",e.target.value)}><option value="">Choose BOM</option>{active.map((b: Row) => <option key={b.id} value={b.id}>{b.name} · {name(b.output)}</option>)}</select></label>
      <label>Quantity to manufacture<input required type="number" min="0.000001" max="1000000000" step="0.000001" value={inputs.qty} onChange={e => update("qty",e.target.value)} /></label>
      <label>Planning warehouse<select required value={inputs.warehouse} onChange={e => update("warehouse",e.target.value)}>{state.warehouses.filter((w: Row) => w.active !== false).map((w: Row) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
    </div>
    {outputs.filter(id => id !== root?.output && active.filter((b: Row) => b.output === id).length > 1).map(id => <label key={id}>BOM version for {name(id)} (if used)<select value={inputs.bomSelections[id] || ""} onChange={e => update("bomSelections",{...inputs.bomSelections,[id]:e.target.value})}><option value="">Select version if included in this plan</option>{active.filter((b: Row) => b.output === id).map((b: Row) => <option key={b.id} value={b.id}>{b.name} · {b.id}</option>)}</select></label>)}
    <label><input type="checkbox" checked={inputs.createPurchaseRequests} onChange={e => update("createPurchaseRequests", e.target.checked)} /> Also create pending purchase requests for raw-material shortages</label>
    <button disabled={disabled}>Validate and preview plan</button></fieldset></form>
    {message && <p role="alert">{message}</p>}
    {preview && <><p>{preview.basis} Preview does not reserve stock. Component jobs are listed before their parent jobs.</p>
      <div className="table-wrap"><table><thead><tr><th>Item</th><th>Required</th><th>Usable / reserved</th><th>Stock used</th><th>Shortage</th></tr></thead><tbody>{preview.rows.map((r: Row) => <tr key={r.item}><td>{name(r.item)}</td><td>{r.grossQty}</td><td>{r.availableQty} / {r.reservedQty}</td><td>{r.stockUsed}</td><td>{r.shortageQty}</td></tr>)}</tbody></table></div>
      <h3>Draft production orders</h3>{preview.production.map((r: Row) => <p key={r.item}>{name(r.item)} · {r.qty} · BOM {r.bom}</p>)}
      <h3>Raw-material purchasing needs</h3>{!preview.purchases.length && <p>No raw-material shortage.</p>}{preview.purchases.map((r: Row) => <p key={r.item}>{name(r.item)} · buy {r.qty} (shortage {r.shortageQty}) {r.blockedReason && <strong>· {r.blockedReason}</strong>}</p>)}
      <p>Creating the plan records draft production orders and, if selected, pending purchase requests. Release, stock reservation, purchasing approval, consumption and output posting remain explicit steps.</p>
      <button disabled={disabled || (preview.createPurchaseRequests && preview.purchases.some((p: Row) => p.blockedReason))} onClick={async () => {
        setPending(true);
        try {if (await command("createMaterialPlan", {...inputs, qty:Number(inputs.qty), previewHash:preview.previewHash})) {setPreview(null); setMessage("Plan created. Review the draft production orders and any pending purchase request.");}}
        finally {setPending(false);}
      }}>Create reviewed plan</button>
    </>}
  </section>;
}
