# ERP industry-style synthetic implementation pack

**Company:** Aster Precision Components Pvt Ltd (fictional) | **Jurisdiction:** India | **Currency:** INR | **As of:** 2026-10-30

Contains CSV seed data, configurable policies, sample approvals, infrastructure/security/recovery requirements, test cases, benchmarks and expected totals. All names, IDs, GSTINs and bank entries are synthetic and are **not legal/tax advice**. No production credentials, bank connections or approved accounting policies are included.

## Quick start
1. Read `docs/IMPLEMENTATION_GUIDE.md`.
2. Import `data/` CSV files in dependency order: company → customers/vendors/items/warehouses → BOM and stock → transactional tables → journals.
3. Load `config/` JSON as draft tenant settings.
4. Compare imports against `validation/expected_totals.json` and run `data/acceptance_tests.csv`.
5. Have a qualified accountant approve actual policies before using real business data.

**Important consistency note:** The trial balance is a standalone opening snapshot, while October transactions and the bank statement are separate scenario fixtures. They must not be aggregated into a single closing ledger without a posting/reconciliation exercise. The supplier invoice intentionally differs from PO and receipt amounts to test exception handling.
