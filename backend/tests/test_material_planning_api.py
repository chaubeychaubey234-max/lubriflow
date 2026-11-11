from test_api import mutation

pytest_plugins = ['test_api']


def test_plan_preview_and_persistence(client):
    assert mutation(client,'settings',dict(modules=dict(manufacturing=True))).status_code == 200
    supplier = mutation(client,'supplier',dict(name='Assembly vendor')).json()['result']['id']
    items = [mutation(client,'item',dict(name=name,supplier=supplier,unit='pcs',price=1,target=100)).json()['result']['id']
             for name in ['Raw component','Finished assembly']]
    bom = mutation(client,'bom',dict(name='Assembly v1',output=items[1],outputQty=1,
        lines=[dict(item=items[0],qty=2)])).json()['result']['id']
    data = dict(bom=bom,qty=3,warehouse='WH-MAIN',reference='API-PLAN',createPurchaseRequests=True)
    before = client.get('/api/workspace').json()
    preview = client.post('/api/material-plan-preview',json=data)
    assert preview.status_code == 200,preview.text
    assert client.get('/api/workspace').json()['revision'] == before['revision']
    response = mutation(client,'createMaterialPlan',dict(data,previewHash=preview.json()['previewHash']))
    assert response.status_code == 200,response.text
    state = client.get('/api/workspace').json()['state']
    assert state['productionOrders'][0]['planningReference'] == 'API-PLAN'
    assert state['requisitions'][0]['status'] == 'Pending'
    assert state['requisitions'][0]['lines'][0]['qty'] == 6
    assert not state['stockMoves'] and not state['journal']
    assert mutation(client,'createMaterialPlan',dict(data,previewHash=preview.json()['previewHash'])).status_code == 400


def test_atomic_state_save_persists_items_before_new_bom_lines(client):
    from lubriflow.db import Session
    from lubriflow.models import User
    from lubriflow.repository import tenant_lock, load, save
    from test_material_planning import fixture
    user_id = client.get('/api/auth/me').json()['id']
    with Session.begin() as db:
        tenant = tenant_lock(db, db.get(User, user_id).tenant_id)
        state = load(db,tenant)
        from lubriflow.domain import act
        from test_domain import ADMIN
        act(state,'supplier',dict(name='Fixture supplier'),ADMIN)
        _, _, _, _, data = fixture(state)
        save(db,tenant,state)
    preview = client.post('/api/material-plan-preview',json=data)
    assert preview.status_code == 200,preview.text
    assert len(preview.json()['production']) == 2


def test_loaded_settings_do_not_alias_persisted_nested_values(client):
    from lubriflow.db import Session
    from lubriflow.models import User
    from lubriflow.repository import tenant_lock, load
    user_id = client.get('/api/auth/me').json()['id']
    with Session.begin() as db:
        tenant = tenant_lock(db,db.get(User,user_id).tenant_id)
        original = tenant.settings['modules']['manufacturing']
        state = load(db,tenant)
        state['settings']['modules']['manufacturing'] = not original
        assert tenant.settings['modules']['manufacturing'] == original
