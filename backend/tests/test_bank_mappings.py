from test_domain import ADMIN
from lubriflow.bank_import import import_statement, save_mapping
from lubriflow.domain import empty, act, RuleError, today
import pytest


def test_custom_bank_mapping_parses_nonstandard_headers_and_delimiter():
    state = empty("Mapping company")
    profile = save_mapping(
        state,
        {
            "name": "Semicolon bank export",
            "delimiter": ";",
            "columns": {
                "date": "Booked",
                "reference": "Ref",
                "money_in": "Credit",
                "money_out": "Debit",
                "description": "Narrative",
                "balance": "Running",
            },
        },
        ADMIN,
    )
    csv = "Booked;Ref;Credit;Debit;Narrative;Running\n2026-11-01;MAP-1;50;;Customer receipt;150"
    preview = import_statement(
        state,
        dict(bankLedger="LED-BANK", statementCurrency="USD", openingBalance=100, csv=csv, mappingId=profile["id"]),
        ADMIN,
        preview=True,
    )
    assert preview["rowCount"] == 1
    assert preview["rows"][0]["reference"] == "MAP-1"


def test_mapping_requires_unique_source_headers():
    state = empty()
    try:
        save_mapping(state, {"name": "Invalid", "columns": {"date": "same", "reference": "same"}}, ADMIN)
    except ValueError as error:
        assert "only once" in str(error)
    else:
        raise AssertionError("duplicate mapping headers must be rejected")


def test_command_mapping_edit_invalidates_preview_and_blank_optional_columns_persist():
    state = empty()
    profile = act(state, 'bankImportMapping', dict(name='Bank', columns={'balance': '', 'description': ''}), ADMIN)
    assert profile['columns']['balance'] == ''
    data = dict(bankLedger='LED-BANK', statementCurrency='USD', mappingId=profile['id'],
                csv=f'date,reference,money_in,money_out\n{today()},A,10,0')
    data['previewHash'] = import_statement(state, data, ADMIN, preview=True)['previewHash']
    act(state, 'bankImportMapping', dict(id=profile['id'], name='Bank', delimiter=';'), ADMIN)
    with pytest.raises(RuleError, match='Preview'):
        act(state, 'bankStatementImport', data, ADMIN)
    assert state['bankStatements'] == []


def test_mapping_command_denies_viewer():
    with pytest.raises(RuleError):
        act(empty(), 'bankImportMapping', {'name': 'Bank'}, {'id': 'viewer', 'role': 'viewer'})
