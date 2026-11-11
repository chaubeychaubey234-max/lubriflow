from test_api import mutation
from lubriflow.domain import today

pytest_plugins = ['test_api']


def test_preview_commit_and_duplicate_are_transactional(client):
    before = client.get('/api/workspace').json()
    data = dict(bankLedger='LED-BANK', statementCurrency=before['state']['settings']['currency'],
        csv=f'date,reference,money_in,money_out\n{today()},IMPORT-1,10,0', openingBalance=None)
    preview = client.post('/api/bank-import-preview', json=data)
    assert preview.status_code == 200, preview.text
    assert client.get('/api/workspace').json()['revision'] == before['revision']
    data['previewHash'] = preview.json()['previewHash']
    saved = mutation(client, 'bankStatementImport', data)
    assert saved.status_code == 200, saved.text
    statement = saved.json()['result']['rows'][0]['id']
    matches = client.get('/api/bank-match-suggestions/'+statement)
    assert matches.status_code == 200 and matches.json()['candidates'] == []
    revision = client.get('/api/workspace').json()['revision']
    assert mutation(client, 'bankStatementImport', data).status_code == 400
    assert client.get('/api/workspace').json()['revision'] == revision


def test_bank_preview_and_suggestions_require_finance_access(client):
    from lubriflow.db import Session
    from lubriflow.models import User
    user_id = client.get('/api/auth/me').json()['id']
    with Session.begin() as db:
        user = db.get(User, user_id)
        user.role = 'viewer'
    data = dict(bankLedger='LED-BANK', statementCurrency='USD',
        csv=f'date,reference,money_in,money_out\n{today()},NO-ACCESS,10,0')
    assert client.post('/api/bank-import-preview', json=data).status_code == 403
    assert client.get('/api/bank-match-suggestions/unknown').status_code == 403
    assert mutation(client, 'bankStatementImport', data).status_code == 400
