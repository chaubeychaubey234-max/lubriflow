from uuid import uuid4
from test_api import mutation
from lubriflow.domain import today

pytest_plugins = ['test_api']


def test_forecast_api_and_langgraph_use_same_approval_path(client):
    from langgraph.checkpoint.memory import InMemorySaver
    from lubriflow.automation import build_graph
    supplier = mutation(client, 'supplier', dict(name='Planning supplier')).json()['result']['id']
    assert mutation(client, 'approveSupplier', dict(id=supplier, approved=True)).status_code == 200
    item = mutation(client, 'item', dict(name='Planning item', supplier=supplier, unit='pcs', stock=100,
        price=1, target=100, reorder=5, packSize=12)).json()['result']['id']
    assert mutation(client, 'stockIssue', dict(item=item, qty=99, reason='Consumption', date=today())).status_code == 200
    assert mutation(client, 'settings', dict(mode='automatic', autoReorder=True, reorderMethod='forecast')).status_code == 200
    insights = client.get('/api/procurement-insights')
    assert insights.status_code == 200, insights.text
    assert insights.json()['forecastPurchaseRecommendations'][0]['suggestedQty'] == 108
    from lubriflow.db import Session
    from lubriflow.models import User
    with Session() as db:
        tenant = db.get(User, client.get('/api/auth/me').json()['id']).tenant_id
    graph = build_graph(InMemorySaver())
    run = str(uuid4())
    result = graph.invoke(dict(tenant_id=tenant, run_id=run), {'configurable': {'thread_id':run}})
    assert result['completed'] == 1 and not result['skipped']
    state = client.get('/api/workspace').json()['state']
    assert len(state['requisitions']) == 1 and state['requisitions'][0]['status'] == 'Pending'
    assert state['requisitions'][0]['planningEvidence']['suggestedQty'] == 108
    assert mutation(client, 'forecastRequisition', dict(item=item)).status_code == 400
    assert not state['orders']
