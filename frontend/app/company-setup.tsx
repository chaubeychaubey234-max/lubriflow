"use client";
import { useState } from 'react';
import { Row } from './forms';

export default function CompanySetup({settings, busy, command}: {settings: Row; busy: boolean; command: (action: string, data: Row, close?: boolean) => Promise<boolean | undefined>}) {
  const [review, setReview] = useState<Row | null>(null);
  const [saved, setSaved] = useState(false);
  const choices: Record<string, string[]> = {
    legalEntityType: ['company', 'partnership', 'sole-proprietor', 'non-profit', 'government'],
    industryTemplate: ['general', 'trading', 'manufacturing', 'services', 'construction', 'healthcare', 'food', 'chemicals'],
    taxRegistrationStatus: ['registered', 'not-registered', 'exempt', 'pending'],
  };
  const fields = [['company', 'Company name'], ['country', 'Country code (for example AE)'],
    ['legalEntityType', 'Legal entity'], ['industryTemplate', 'Industry template'],
    ['taxRegistrationStatus', 'Tax registration'], ['currency', 'Base currency (for example AED)'],
    ['timezone', 'Timezone (for example Asia/Dubai)'], ['fiscalYearStart', 'Financial-year start (MM-DD)'],
    ['taxRegime', 'Tax regime name']];
  return <section className="panel"><h2>Guided company setup</h2>
    <p>Enter your company details, then review the settings before applying them.</p>
    <form onSubmit={e => {e.preventDefault(); setSaved(false); setReview(Object.fromEntries(new FormData(e.currentTarget)));}}>
      <div className="grid">{fields.map(([key, label]) => <label key={key}>{label}
        {choices[key] ? <select name={key} defaultValue={settings[key] || ''} required disabled={busy || !!review}>
          <option value="">Choose an option</option>{choices[key].map(value => <option key={value} value={value}>{value}</option>)}
        </select> : <input name={key} defaultValue={settings[key] || ''} required maxLength={200} disabled={busy || !!review} />}
      </label>)}</div>
      {!review && <button disabled={busy}>Review company setup</button>}
    </form>
    {review && <div><h3>Review changes</h3><dl>{fields.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{review[key]}</dd></div>)}</dl>
      <p>Procurement, inventory and accounting will be enabled. Trading and services also enable sales; manufacturing enables sales and production; construction enables projects. Existing enabled modules stay enabled.</p>
      <p>Healthcare, food and chemicals currently use the general modules. Their specialist compliance packages are still pending. Country and tax details do not install statutory reporting or e-invoicing. Automation and external sending keep their current settings.</p>
      <button disabled={busy} onClick={() => setReview(null)}>Back to edit</button>
      <button disabled={busy} onClick={async () => {if (await command('configureCompany', review, false)) {setReview(null); setSaved(true);}}}>Apply company setup</button>
    </div>}
    {saved && <p role="status">Company setup applied successfully.</p>}
  </section>;
}
