"""Repeatable HTTP baseline on a dedicated synthetic test database only."""
import asyncio
import json
import os
import secrets
import statistics
import time
from uuid import uuid4
from pathlib import Path
import httpx
from lubriflow.db import Session
from lubriflow.models import Tenant, User
from lubriflow.domain import empty, act
from lubriflow.repository import save
from lubriflow.auth import hash_password

async def main():
    if 'lubriflow_test' not in os.environ.get('DATABASE_URL', ''):
        raise SystemExit('Dedicated test database required')
    email, password = str(uuid4())+'@example.test', secrets.token_urlsafe(24)
    with Session.begin() as db:
        tenant = Tenant(name='Performance synthetic', settings={}, series={})
        db.add(tenant)
        db.flush()
        state = empty(tenant.name)
        actor = dict(id=str(uuid4()), name='Load setup', role='admin')
        supplier = act(state, 'supplier', {'name':'Synthetic supplier'}, actor)
        for i in range(500):
            act(state, 'item', dict(name=f'Item {i}', unit='EA', supplier=supplier['id'], price=10, reorder=0, target=10), actor)
        save(db, tenant, state)
        db.add(User(tenant_id=tenant.id,email=email,name='Load tester',role='admin',password_hash=hash_password(password)))
    base = os.environ.get('PERF_BASE_URL','http://127.0.0.1:18000')
    async with httpx.AsyncClient(base_url=base, timeout=60, headers={'Origin':'http://localhost:3000','X-Lubriflow-Request':'1'}) as c:
        response=await c.post('/api/auth/login',json=dict(email=email,password=password))
        response.raise_for_status()
        (await c.get('/api/workspace')).raise_for_status()
        results=[]
        for concurrency in [1,5,10]:
            sem=asyncio.Semaphore(concurrency)
            async def request():
                async with sem:
                    start=time.perf_counter()
                    r=await c.get('/api/workspace')
                    return (time.perf_counter()-start)*1000,r.status_code,len(r.content)
            start=time.perf_counter()
            rows=await asyncio.gather(*(request() for _ in range(50)))
            elapsed=time.perf_counter()-start
            times=sorted(row[0] for row in rows)
            results.append(dict(concurrency=concurrency,requests=50,p50_ms=round(statistics.median(times),2),p95_ms=round(times[47],2),p99_ms=round(times[49],2),requests_per_second=round(50/elapsed,2),unexpected_errors=sum(row[1]!=200 for row in rows),response_bytes=rows[0][2]))
        writes=[]
        for i in range(20):
            revision=(await c.get('/api/workspace')).json()['revision']
            start=time.perf_counter()
            r=await c.post('/api/workspace',json=dict(action='supplier',data={'name':f'HTTP load vendor {i}'},revision=revision,requestId=str(uuid4())))
            writes.append(((time.perf_counter()-start)*1000,r.status_code))
        revision=(await c.get('/api/workspace')).json()['revision']
        conflicts=await asyncio.gather(*(c.post('/api/workspace',json=dict(action='supplier',data={'name':f'Contended {i}'},revision=revision,requestId=str(uuid4()))) for i in range(5)))
        write_summary=dict(requests=20,p95_ms=round(sorted(t for t,_ in writes)[18],2),unexpected_errors=sum(code!=200 for _,code in writes),concurrent_write_statuses=sorted(r.status_code for r in conflicts))
        await c.post('/api/auth/logout',json={})
    report=dict(scope='Local HTTP read baseline, 500 synthetic items; 20 sequential writes and 5 contended writes; not production capacity',results=results,writes=write_summary)
    Path('docs/performance-results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if any(r['unexpected_errors'] for r in results) or write_summary['unexpected_errors'] or write_summary['concurrent_write_statuses'] != [200,409,409,409,409]:
        raise SystemExit(1)

if __name__=='__main__':
    asyncio.run(main())
