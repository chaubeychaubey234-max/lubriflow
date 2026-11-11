-- Immutable initial PostgreSQL schema.

CREATE TABLE login_attempts (
	key VARCHAR(64) NOT NULL, 
	failures INTEGER NOT NULL, 
	window_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE tenants (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	revision INTEGER NOT NULL, 
	settings JSONB NOT NULL, 
	series JSONB NOT NULL, 
	next_run TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE audit_events (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	actor_id VARCHAR(100) NOT NULL, 
	action VARCHAR(100) NOT NULL, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_audit_events_at ON audit_events (at);

CREATE TABLE automation_runs (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	requested_by VARCHAR(100) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	result JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_automation_runs_status ON automation_runs (status);

CREATE INDEX ix_automation_runs_tenant_id ON automation_runs (tenant_id);

CREATE UNIQUE INDEX one_active_run_per_tenant ON automation_runs (tenant_id) WHERE status IN ('Queued','Running');

CREATE TABLE business_accounts (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_accounts_date ON business_accounts (date);

CREATE INDEX ix_business_accounts_status ON business_accounts (status);

CREATE INDEX ix_business_accounts_supplier ON business_accounts (supplier);

CREATE TABLE business_attachments (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_attachments_date ON business_attachments (date);

CREATE INDEX ix_business_attachments_status ON business_attachments (status);

CREATE INDEX ix_business_attachments_supplier ON business_attachments (supplier);

CREATE TABLE business_comments (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_comments_date ON business_comments (date);

CREATE INDEX ix_business_comments_status ON business_comments (status);

CREATE INDEX ix_business_comments_supplier ON business_comments (supplier);

CREATE TABLE business_costcentres (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_costcentres_date ON business_costcentres (date);

CREATE INDEX ix_business_costcentres_status ON business_costcentres (status);

CREATE INDEX ix_business_costcentres_supplier ON business_costcentres (supplier);

CREATE TABLE business_credits (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_credits_date ON business_credits (date);

CREATE INDEX ix_business_credits_status ON business_credits (status);

CREATE INDEX ix_business_credits_supplier ON business_credits (supplier);

CREATE TABLE business_drafts (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_drafts_date ON business_drafts (date);

CREATE INDEX ix_business_drafts_status ON business_drafts (status);

CREATE INDEX ix_business_drafts_supplier ON business_drafts (supplier);

CREATE TABLE business_invoices (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_invoices_date ON business_invoices (date);

CREATE INDEX ix_business_invoices_status ON business_invoices (status);

CREATE INDEX ix_business_invoices_supplier ON business_invoices (supplier);

CREATE TABLE business_items (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_items_date ON business_items (date);

CREATE INDEX ix_business_items_status ON business_items (status);

CREATE INDEX ix_business_items_supplier ON business_items (supplier);

CREATE TABLE business_journal (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_journal_date ON business_journal (date);

CREATE INDEX ix_business_journal_status ON business_journal (status);

CREATE INDEX ix_business_journal_supplier ON business_journal (supplier);

CREATE TABLE business_ledgers (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_ledgers_date ON business_ledgers (date);

CREATE INDEX ix_business_ledgers_status ON business_ledgers (status);

CREATE INDEX ix_business_ledgers_supplier ON business_ledgers (supplier);

CREATE TABLE business_orders (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_orders_date ON business_orders (date);

CREATE INDEX ix_business_orders_status ON business_orders (status);

CREATE INDEX ix_business_orders_supplier ON business_orders (supplier);

CREATE TABLE business_payments (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_payments_date ON business_payments (date);

CREATE INDEX ix_business_payments_status ON business_payments (status);

CREATE INDEX ix_business_payments_supplier ON business_payments (supplier);

CREATE TABLE business_portalsubmissions (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_portalsubmissions_date ON business_portalsubmissions (date);

CREATE INDEX ix_business_portalsubmissions_status ON business_portalsubmissions (status);

CREATE INDEX ix_business_portalsubmissions_supplier ON business_portalsubmissions (supplier);

CREATE TABLE business_prices (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_prices_date ON business_prices (date);

CREATE INDEX ix_business_prices_status ON business_prices (status);

CREATE INDEX ix_business_prices_supplier ON business_prices (supplier);

CREATE TABLE business_quotes (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_quotes_date ON business_quotes (date);

CREATE INDEX ix_business_quotes_status ON business_quotes (status);

CREATE INDEX ix_business_quotes_supplier ON business_quotes (supplier);

CREATE TABLE business_receipts (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_receipts_date ON business_receipts (date);

CREATE INDEX ix_business_receipts_status ON business_receipts (status);

CREATE INDEX ix_business_receipts_supplier ON business_receipts (supplier);

CREATE TABLE business_requisitions (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_requisitions_date ON business_requisitions (date);

CREATE INDEX ix_business_requisitions_status ON business_requisitions (status);

CREATE INDEX ix_business_requisitions_supplier ON business_requisitions (supplier);

CREATE TABLE business_returns (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_returns_date ON business_returns (date);

CREATE INDEX ix_business_returns_status ON business_returns (status);

CREATE INDEX ix_business_returns_supplier ON business_returns (supplier);

CREATE TABLE business_stockmoves (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_stockmoves_date ON business_stockmoves (date);

CREATE INDEX ix_business_stockmoves_status ON business_stockmoves (status);

CREATE INDEX ix_business_stockmoves_supplier ON business_stockmoves (supplier);

CREATE TABLE business_suppliers (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_suppliers_date ON business_suppliers (date);

CREATE INDEX ix_business_suppliers_status ON business_suppliers (status);

CREATE INDEX ix_business_suppliers_supplier ON business_suppliers (supplier);

CREATE TABLE business_warehouses (
	tenant_id VARCHAR(36) NOT NULL, 
	id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(50), 
	supplier VARCHAR(100), 
	date VARCHAR(10), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_business_warehouses_date ON business_warehouses (date);

CREATE INDEX ix_business_warehouses_status ON business_warehouses (status);

CREATE INDEX ix_business_warehouses_supplier ON business_warehouses (supplier);

CREATE TABLE mutations (
	tenant_id VARCHAR(36) NOT NULL, 
	request_id VARCHAR(120) NOT NULL, 
	actor_id VARCHAR(100) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	result JSONB NOT NULL, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (tenant_id, request_id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	email VARCHAR(254) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	password_hash VARCHAR(300) NOT NULL, 
	role VARCHAR(30) NOT NULL, 
	supplier_id VARCHAR(100), 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	UNIQUE (email)
);

CREATE INDEX ix_users_tenant_id ON users (tenant_id);

CREATE TABLE document_lines (
	tenant_id VARCHAR(36) NOT NULL, 
	collection VARCHAR(40) NOT NULL, 
	record_id VARCHAR(100) NOT NULL, 
	position INTEGER NOT NULL, 
	item_id VARCHAR(100) NOT NULL, 
	quantity NUMERIC(20, 6) NOT NULL, 
	unit_price NUMERIC(20, 2) NOT NULL, 
	discount NUMERIC(5, 2) NOT NULL, 
	tax_rate NUMERIC(5, 2), 
	payload JSONB NOT NULL, 
	PRIMARY KEY (tenant_id, collection, record_id, position), 
	FOREIGN KEY(tenant_id, item_id) REFERENCES business_items (tenant_id, id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_document_lines_item_id ON document_lines (item_id);

CREATE TABLE login_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_login_sessions_user_id ON login_sessions (user_id);
