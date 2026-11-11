# LubriFlow

**Industrial Purchasing, Material Planning & ERP Platform**

LubriFlow is a specialized Enterprise Resource Planning (ERP) and automated procurement platform built for industrial lubricants, blending plants, packaging facilities, and discrete manufacturing operations. It combines strict internal accounting controls, automated purchase workflows, three-way invoice matching, multi-tier approvals, multi-warehouse stock management, and supplier collaboration in a single integrated solution.

---

## Key Features

### 1. End-to-End Procurement (P2P)
* **Requisitions & RFQs:** Departmental purchase requisitions (PR) and Requests for Quotation (RFQ) with multi-supplier comparison baskets.
* **Purchase Orders:** Complete purchase order lifecycle with versioning, revision history, amendment tracking, and pre-closures.
* **Goods Receipts & Quality Inspection:** Batch/lot tracking, test certificates, manufacturing and expiry dates, vehicle/transporter records, and quality accept/reject gates before stock release.
* **Three-Way Matching:** Automated verification of PO line rates, accepted receipt quantities (GRN), and supplier invoices with configurable price and rounding tolerances.
* **Payment Register & Settlements:** Support for bank payments, supplier advances, credit notes, and supplier returns with automatic balance reconciliation.

### 2. Multi-Tier Approval Matrix & Governance
* **Configurable Amount Thresholds:** Rules routed dynamically based on currency base amounts and organizational roles.
* **Separation of Duties:** Enforces that voucher creators cannot approve their own requests; prevents single users from signing off on consecutive stages.
* **Temporary Delegation:** Administrative delegation of approval authority for defined time windows with audit logging.
* **Overdue Escalations:** Automation worker identifies delayed approval stages and triggers escalations for supervisory review.

### 3. Inventory & Warehouse Management
* **Multi-Warehouse Locations:** Real-time balance tracking across raw materials, packaging, and finished goods warehouses.
* **Batch, Lot & Serial Tracking:** Full traceability from raw base oil receipts to intermediate batches and final packaged lubricants.
* **Barcode Support:** Native barcode lookup and scanner integration for fast material receiving and physical counts.
* **Stock Movements & Counts:** Physical stock counts, adjustments, reservations, and landed cost allocations.

### 4. Manufacturing & Material Requirements Planning (MRP)
* **Multi-Level Bills of Materials (BOM):** Recipe formulations with component yields, pack sizes, and scrap percentages.
* **Production Orders:** Work orders with material issue, partial consumption, output yield, and batch genealogy.
* **Automated Material Planning:** BOM explosion preview identifying usable stock, reserved inventory, and immediate purchase shortages.

### 5. Financial Accounting & Books
* **Dual-Entry General Ledger:** Automatic journal generation on invoice posting, payments, returns, and inventory transfers.
* **Financial Reports:** Real-time Trial Balance, Profit & Loss (P&L), Balance Sheet, Aged Payables, and Purchase Register.
* **Multi-Currency:** Transaction currency handling with explicit exchange rates and FX revaluation capabilities.
* **Bank Reconciliation:** Bank statement import with rule-based matching against posted vouchers.

### 6. Supplier Collaboration Portal
* **Dedicated Vendor Interface:** Restricted external portal for qualified suppliers.
* **Order Management:** Real-time access to issued purchase orders with direct acceptance or decline responses.
* **Invoice Submission:** Direct upload of vendor billing details for finance review and automated 3-way matching.

### 7. Automation Engine
* **Policy-Driven Execution:** Background worker evaluates replenishment rules, auto-conversion of approved PRs, automated approvals within defined thresholds, and batch invoice matching.
* **Idempotency Protection:** LangGraph state machine backed by persistent checkpointing ensures guaranteed once-only command execution.

---

## Technology Stack

| Component | Technology | Details |
|---|---|---|
| **Frontend** | Next.js 15, React 19, TypeScript | App Router, responsive styling, standalone build |
| **API & Business Logic** | FastAPI, Python 3.12+, Pydantic v2 | Strict Decimal arithmetic, domain state machine |
| **Database** | PostgreSQL 16+, SQLAlchemy 2 | Immutable schema history via Alembic migrations |
| **Workflow Engine** | LangGraph, Postgres Checkpointer | Durable background automation execution |
| **Authentication & Security** | Argon2id, Session Cookies, TOTP MFA | Role-based permissions, strict CORS, CSP headers |
| **Packaging** | Docker, Docker Compose | Web, API, database, and background worker containers |

---

## Project Structure

```text
lubriflow/
├── backend/
│   ├── lubriflow/
│   │   ├── domain.py             # Authoritative state transitions & business calculations
│   │   ├── api.py                # Authenticated REST endpoints & middleware
│   │   ├── models.py             # SQLAlchemy database models & schemas
│   │   ├── accounting.py         # General ledger, vouchers, and chart of accounts
│   │   ├── finance.py            # Balance sheet, P&L, aged reports, and journals
│   │   ├── approval_policy.py    # Approval matrix routing, delegation & escalation
│   │   ├── automation.py         # LangGraph state machine for background tasks
│   │   ├── worker.py             # Continuous worker for automation & escalations
│   │   ├── inventory.py          # Stock positions, movements & landed costs
│   │   ├── manufacturing.py      # BOM explosion & production work orders
│   │   ├── material_planning.py  # MRP shortage calculations & demand previews
│   │   └── security.py           # Multi-factor authentication (MFA/TOTP)
│   ├── migrations/               # Alembic database migration versions
│   └── tests/                    # Comprehensive unit and integration test suite
├── frontend/
│   ├── app/
│   │   ├── page.tsx              # Main ERP workspace & navigation
│   │   ├── forms.ts              # Form schemas, validations & formatting helpers
│   │   ├── procurement-dashboard.tsx # Replenishment & quotation analysis
│   │   ├── material-planner.tsx  # Interactive BOM explosion & planning interface
│   │   ├── accounting-workbench.tsx  # Financial vouchers & ledger entry
│   │   └── styles.css            # Custom responsive design system
│   ├── next.config.ts            # Proxy rewrites and security headers
│   └── package.json              # Frontend dependencies and build scripts
├── sample_data/
│   └── erp_sample_pack/          # Verification datasets, CSV fixtures & data dictionary
├── scripts/
│   ├── prepare_demo.py           # Starter tenant and role account seed script
│   ├── http_smoke.py             # End-to-end integration smoke testing
│   └── validate_sample_pack.py   # Dataset validation and accounting checks
├── compose.yaml                  # Production Docker Compose orchestration
└── pyproject.toml                # Python package metadata and dependencies
```

---

## Quick Start

### Option A: Running with Docker (Recommended)

1. **Clone the repository:**
   ```sh
   git clone https://github.com/chaubeychaubey234-max/lubriflow.git
   cd lubriflow
   ```

2. **Configure environment:**
   ```sh
   cp .env.example .env
   # Edit .env and set strong secrets for POSTGRES_PASSWORD and MFA_ENCRYPTION_KEY
   ```

3. **Start the platform:**
   ```sh
   docker compose up --build -d
   ```

4. **Initialize company and administrator:**
   ```sh
   docker compose exec api uv run python -m lubriflow.cli
   ```
   Follow the prompts to enter your company name, admin email, and initial password.

5. **Access the application:**
   * **Web Workspace:** [http://localhost:3000](http://localhost:3000)
   * **API Swagger Docs:** [http://localhost:3000/api/docs](http://localhost:3000/api/docs)

---

### Option B: Local Development Setup

#### Prerequisites
* Python 3.12 or newer with `uv` package manager
* Node.js 22+ with `npm`
* PostgreSQL 14+ running locally

#### 1. Backend Setup
```sh
# Install Python dependencies
uv sync --frozen

# Apply database migrations
uv run alembic upgrade head

# Start FastAPI server
uv run python -m uvicorn lubriflow.api:app --host 127.0.0.1 --port 8000 --reload
```

#### 2. Worker Setup (in a separate terminal)
```sh
# Start the background automation worker
uv run python -m lubriflow.worker
```

#### 3. Frontend Setup (in a separate terminal)
```sh
cd frontend
npm ci
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to view the application.

---

## Sample Data & Seeding

A starter seed script is included to quickly populate a working test environment with realistic items, suppliers, approval routes, and orders:

```sh
uv run python scripts/prepare_demo.py
```
This script creates pre-configured role accounts (Administrator, Buyer, Approver, Finance, Stores, Quality Inspector, and Supplier). Generated credentials are saved locally to `var/demo-access.json`.

Full industry fixtures and verification datasets are available in the `sample_data/erp_sample_pack/` directory.

---

## Quality Assurance & Tests

Run the test suite to verify domain logic, database operations, and frontend builds:

```sh
# Run backend test suite
uv run pytest

# Check code formatting and linting
uv run ruff check backend

# Frontend TypeScript verification
npm --prefix frontend run typecheck

# Frontend production build
npm --prefix frontend run build
```

---

## Security

* **Separation of Duties:** Built-in safeguards ensure segregation between purchase authorization, goods receipt, and payment execution.
* **Session Management:** Secure server-side sessions with HTTP-only, SameSite cookies.
* **MFA Support:** Time-based One-Time Password (TOTP) two-factor authentication with recovery codes.
* **Audit Trail:** Every mutation, voucher entry, approval decision, and system action is permanently recorded in the audit event log.

---

## Author

**Ankush Chaubey**  
GitHub: [@chaubeychaubey234-max](https://github.com/chaubeychaubey234-max)
