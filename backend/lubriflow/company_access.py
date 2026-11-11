"""Explicit company-access resolution; never mutate the global User identity."""
from fastapi import HTTPException
from .models import CompanyMembership

STAFF_ROLES = {'admin', 'buyer', 'requester', 'approver', 'stores', 'quality', 'production', 'sales', 'finance', 'viewer'}


def company_role(db, user, tenant_id):
    if not user.active:
        raise HTTPException(401, 'Sign in required.')
    membership = db.get(CompanyMembership, (user.id, tenant_id))
    if membership is not None:
        if not membership.active or membership.role not in STAFF_ROLES:
            raise HTTPException(403, 'Company access is not available.')
        return membership.role
    # Legacy home-company access remains until the membership cutover is complete.
    if tenant_id == user.tenant_id and user.role in STAFF_ROLES:
        return user.role
    raise HTTPException(403, 'Company access is not available.')
