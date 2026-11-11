from copy import deepcopy
import pytest
from test_domain import ADMIN, order, issue, receipt, bill, post
from lubriflow.domain import act, get, today, RuleError
pytest_plugins=["test_domain"]

def test_unmatch_required_before_payment_reversal(s):
    po=order(s);issue(s,po);receipt(s,po)
    inv=bill(s,po);post(s,inv)
    pay=act(s,"pay",dict(id=inv,amount=52.5,reference="PAY"),ADMIN)
    stmt=act(s,"bankStatement",dict(amount=52.5,reference="BANK",direction="credit"),ADMIN)
    act(s,"reconcileBank",dict(statement=stmt["id"],collection="payments",transaction=pay["id"]),ADMIN)
    before=deepcopy(s)
    with pytest.raises(RuleError,match="Unmatch"):
        act(s,"reversePayment",dict(id=pay["id"],reason="Correction"),ADMIN)
    assert s==before
    act(s,"unmatchBank",dict(statement=stmt["id"],reason="Wrong match"),ADMIN)
    assert get(s,"bankStatements",stmt["id"])["matchHistory"][0]["reason"]=="Wrong match"
    act(s,"reversePayment",dict(id=pay["id"],reason="Correction"),ADMIN)
    assert get(s,"payments",pay["id"])["status"]=="Reversed"

def test_locked_statement_cannot_be_matched(s):
    stmt=act(s,"bankStatement",dict(amount=1,reference="LOCKED",direction="credit"),ADMIN)
    act(s,"closePeriod",dict(through=today()),ADMIN)
    with pytest.raises(RuleError):
        act(s,"reconcileBank",dict(statement=stmt["id"],collection="payments",transaction="missing"),ADMIN)
