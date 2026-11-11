"use client";
import {useState} from 'react';
import {Row, money} from './forms';

export default function BankSplit({state, busy, command}: {state: Row; busy: boolean; command: (action: string, data: Row, close?: boolean) => Promise<boolean | undefined>}) {
  const [payment, setPayment] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const payments = ['payments', 'customerPayments', 'partyFunds', 'fundRefunds'].flatMap(collection =>
    state[collection].filter((r: Row) => !r.reconciledStatement && r.status !== 'Reversed').map((r: Row) => ({...r, collection, key: `${collection}:${r.id}`})));
  const target = payments.find((r: Row) => r.key === payment);
  const direction = target && (target.collection === 'partyFunds' ? (target.side === 'supplier' ? 'credit' : 'debit') : target.collection === 'fundRefunds' ? (target.side === 'supplier' ? 'debit' : 'credit') : target.collection === 'payments' ? 'credit' : 'debit');
  const rows = target ? state.bankStatements.filter((r: Row) => r.status === 'Unreconciled' && r.bankLedger === target.bankLedger && r.direction === direction) : [];
  const total = rows.filter((r: Row) => selected.includes(r.id)).reduce((n: number, r: Row) => n + Number(r.amount), 0);
  return <section className="panel"><h3>Match one payment to several bank entries</h3>
    <label>Recorded payment or receipt<select value={payment} disabled={busy} onChange={e => {setPayment(e.target.value); setSelected([]);}}>
      <option value="">Choose a transaction</option>{payments.map((r: Row) => <option key={r.key} value={r.key}>{r.id} · {r.reference} · {money(r.amount)}</option>)}
    </select></label>
    {target && <><p>Select entries totalling {money(target.amount)}. Unmatching any entry later will unmatch this whole group.</p>
      {rows.map((r: Row) => <label className="check-label" key={r.id}><input type="checkbox" disabled={busy} checked={selected.includes(r.id)} onChange={e => setSelected(old => e.target.checked ? [...old, r.id] : old.filter(id => id !== r.id))}/>{r.date} · {r.reference} · {money(r.amount)}</label>)}
      <p>Selected total: {money(total)}</p><button disabled={busy || selected.length < 2 || selected.length > 100 || Math.abs(total - Number(target.amount)) > 0.000001} onClick={async () => {
        if (await command('reconcileBankSplit', {collection: target.collection, transaction: target.id, statements: selected}, false)) {setPayment(''); setSelected([]);}
      }}>Reconcile selected bank entries</button></>}
  </section>;
}
