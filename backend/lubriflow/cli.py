"""Interactive administrator setup: uv run python -m lubriflow.cli"""

from getpass import getpass
from sqlalchemy import select
from .db import Session
from .models import Tenant, User
from .auth import hash_password
from .company_defaults import new_uae_company
from .repository import save


def main():
    company = input("Company name: ").strip()
    industry = input('Industry (trading/services) [trading]: ').strip() or 'trading'
    initial_state = new_uae_company(company, industry)
    email = input("Administrator email: ").strip().casefold()
    if not company or "@" not in email:
        raise SystemExit("Company and a valid email are required.")
    password = getpass("Password (12+ characters): ")
    if password != getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    with Session.begin() as db:
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("Email already exists.")
        tenant = Tenant(name=company, settings={}, series={})
        db.add(tenant)
        db.flush()
        save(db, tenant, initial_state)
        db.add(
            User(
                tenant_id=tenant.id,
                email=email,
                name="Administrator",
                role="admin",
                password_hash=hash_password(password),
            )
        )
    print("Company and administrator created.")


if __name__ == "__main__":
    main()
