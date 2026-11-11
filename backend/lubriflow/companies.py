from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from .auth import current_user, staff, role
from .db import database
from .models import CompanyMembership, Tenant, User
from .company_access import company_role

router = APIRouter(prefix='/api/companies')
STAFF_ROLES = {'admin', 'buyer', 'requester', 'approver', 'stores', 'quality', 'production', 'sales', 'finance', 'viewer'}


class MembershipInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    role: str


def active_admin_count(db, tenant_id):
    explicit = set(db.scalars(select(CompanyMembership.user_id).where(
        CompanyMembership.tenant_id == tenant_id, CompanyMembership.active.is_(True), CompanyMembership.role == 'admin')))
    overridden = set(db.scalars(select(CompanyMembership.user_id).where(
        CompanyMembership.tenant_id == tenant_id)))
    legacy = set(db.scalars(select(User.id).where(
        User.tenant_id == tenant_id, User.active.is_(True), User.role == 'admin')))
    return len(explicit | (legacy - overridden))


@router.get('')
def companies(user=Depends(current_user), db=Depends(database)):
    if user.role == 'supplier':
        raise HTTPException(403, 'Supplier access is restricted to the portal.')
    ids = {user.tenant_id}
    ids.update(db.scalars(select(CompanyMembership.tenant_id).where(CompanyMembership.user_id == user.id)))
    result = []
    for tenant in db.scalars(select(Tenant).where(Tenant.id.in_(ids)).order_by(Tenant.name, Tenant.id)):
        try:
            role = company_role(db, user, tenant.id)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            continue
        result.append(dict(id=tenant.id, name=tenant.name, role=role, current=tenant.id == user.tenant_id))
    return dict(companies=result, switchingEnabled=True)


@router.get('/members')
def members(user=Depends(staff), db=Depends(database)):
    role(user, 'admin')
    memberships = {row.user_id: row for row in db.scalars(select(CompanyMembership).where(
        CompanyMembership.tenant_id == user.tenant_id))}
    ids = set(memberships)
    ids.update(db.scalars(select(User.id).where(User.tenant_id == user.tenant_id)))
    results = []
    for person in db.scalars(select(User).where(User.id.in_(ids)).order_by(User.name, User.email)):
        if person.role == 'supplier':
            continue
        membership = memberships.get(person.id)
        if membership:
            results.append(dict(id=person.id, name=person.name, email=person.email, role=membership.role,
                                active=membership.active, explicit=True))
        elif person.active:
            results.append(dict(id=person.id, name=person.name, email=person.email, role=person.role,
                                active=True, explicit=False))
    return results


@router.post('/members')
def upsert_member(body: MembershipInput, user=Depends(staff), db=Depends(database)):
    role(user, 'admin')
    if body.role not in STAFF_ROLES:
        raise HTTPException(400, 'Choose a staff company role.')
    person = db.scalar(select(User).where(User.email == body.email.strip().casefold()))
    if not person or not person.active or person.role == 'supplier':
        raise HTTPException(400, 'Choose an active staff user.')
    membership = db.get(CompanyMembership, (person.id, user.tenant_id))
    old_admin = membership is not None and membership.active and membership.role == 'admin'
    if old_admin and body.role != 'admin' and active_admin_count(db, user.tenant_id) <= 1:
        raise HTTPException(400, 'Keep at least one active company administrator.')
    if membership is None:
        membership = CompanyMembership(user_id=person.id, tenant_id=user.tenant_id, role=body.role, active=True)
        db.add(membership)
    else:
        membership.role, membership.active = body.role, True
    db.commit()
    return dict(id=person.id, email=person.email, role=membership.role, active=True)


@router.post('/members/{user_id}/revoke')
def revoke_member(user_id: str, user=Depends(staff), db=Depends(database)):
    role(user, 'admin')
    if user_id == user.id:
        raise HTTPException(400, 'You cannot revoke your own selected-company access.')
    membership = db.get(CompanyMembership, (user_id, user.tenant_id))
    if not membership or not membership.active:
        raise HTTPException(400, 'Active explicit company membership not found.')
    if membership.role == 'admin' and active_admin_count(db, user.tenant_id) <= 1:
        raise HTTPException(400, 'Keep at least one active company administrator.')
    membership.active = False
    db.commit()
    return dict(ok=True)
