import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import ValidationError
from chatkit.server import StreamingResult
from chatkit.store import NotFoundError
from auth import Auth
from chat import SQLiteChatStore, AikoChatServer
from models import Decision, Login
from store import Conflict, Store

ROOT=Path(__file__).parent
COOKIE='aiko_session'


def create_app(db_path=None,worker=True):
    public_origin=os.environ.get('AIKO_PUBLIC_BASE_URL','').rstrip('/')
    if public_origin:
        parsed=urlsplit(public_origin)
        if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('AIKO_PUBLIC_BASE_URL must be a canonical HTTPS origin.')
        if os.environ.get('AIKO_COOKIE_SECURE')!='1':
            raise ValueError('Hosted mode requires AIKO_COOKIE_SECURE=1.')
    store=Store(db_path or os.environ.get('AIKO_DB',str(ROOT/'aiko-v03.sqlite3')))
    auth=Auth(store)
    chat_store=SQLiteChatStore(store)
    chat=AikoChatServer(chat_store)

    @asynccontextmanager
    async def lifespan(app):
        async def work():
            while True:
                await asyncio.sleep(1)
                await asyncio.to_thread(store.tick)
        task=asyncio.create_task(work()) if worker else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError): await task

    app=FastAPI(title='AIKO Authenticated Runtime',version='0.3.0',lifespan=lifespan)
    app.state.store=store;app.state.auth=auth;app.state.chat=chat
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','[::1]','testserver']+([urlsplit(public_origin).hostname] if public_origin else []))

    @app.middleware('http')
    async def boundary(request,call_next):
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if (origin and origin!=(public_origin or str(request.base_url).rstrip('/'))) or request.headers.get('sec-fetch-site')=='cross-site':
                return JSONResponse({'detail':'Cross-origin mutation rejected.'},status_code=403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    def identity(request:Request):
        session=auth.session(request.cookies.get(COOKIE))
        if request.method not in ('GET','HEAD','OPTIONS'):
            if not hmac.compare_digest(request.headers.get('x-csrf-token',''),session['csrf']):
                raise HTTPException(403,'CSRF-token mangler eller er ugyldig.')
        return session

    @app.get('/healthz')
    def health():
        with store.tx() as db:
            db.execute('SELECT 1').fetchone()
        return {'status':'ok','version':'0.3.1','tool_mode':'simulated'}

    @app.get('/api/chatkit/config')
    def chat_config(user=Depends(identity)):
        key=os.environ.get('AIKO_CHATKIT_DOMAIN_KEY','local-dev' if not public_origin else '')
        if not key: raise HTTPException(503,'Hosted ChatKit domain key is not configured.')
        return {'domain_key':key}

    @app.get('/')
    def index(): return FileResponse(ROOT/'static'/'index.html')

    @app.get('/chat')
    def chat_page(): return FileResponse(ROOT/'static'/'chat.html')

    @app.post('/api/auth/login')
    def login(body:Login,request:Request,response:Response):
        token,user=auth.login(body.username,body.password,request.client.host if request.client else 'local')
        response.set_cookie(COOKIE,token,httponly=True,samesite='strict',max_age=28800,
                            secure=os.environ.get('AIKO_COOKIE_SECURE')=='1',path='/')
        return user

    @app.get('/api/auth/me')
    def me(user=Depends(identity)): return {k:user[k] for k in ('owner','username','csrf')}

    @app.post('/api/auth/logout')
    def logout(request:Request,response:Response,user=Depends(identity)):
        auth.logout(request.cookies[COOKIE]);response.delete_cookie(COOKIE,path='/');return {'ok':True}

    @app.get('/api/runs/current')
    def current(user=Depends(identity)):
        return store.current(user['owner']) or store.create(user['owner'])

    @app.get('/api/runs/{rid}')
    def get_run(rid:str,user=Depends(identity)):
        try: return store.get(rid,user['owner'])
        except KeyError: raise HTTPException(404,'Run not found')

    @app.post('/api/runs',status_code=201)
    def create(user=Depends(identity)): return store.create(user['owner'])

    @app.post('/api/runs/{rid}/decision')
    def decide(rid:str,body:Decision,user=Depends(identity)):
        try: return store.decide(rid,body.model_dump(),user['owner'])
        except KeyError: raise HTTPException(404,'Run not found')
        except Conflict as exc: raise HTTPException(409,str(exc))

    @app.post('/chatkit')
    async def chatkit(request:Request,user=Depends(identity)):
        raw=await request.body()
        if len(raw)>65536: raise HTTPException(413,'Request too large')
        try:
            data=json.loads(raw)
            if not isinstance(data,dict): raise ValueError('Object required')
            allowed={'threads.create','threads.get_by_id','threads.list','threads.add_user_message',
                     'threads.custom_action','threads.update','threads.delete','items.list'}
            if data.get('type') not in allowed: raise HTTPException(400,'Operation disabled')
            params=data.get('params',{})
            if not isinstance(params,dict): raise ValueError('Params must be an object')
            if params.get('thread_id'):
                await chat_store.load_thread(params['thread_id'],user)
            result=await chat.process(raw,user)
        except NotFoundError: raise HTTPException(404,'Thread not found')
        except (ValueError,ValidationError): raise HTTPException(422,'Invalid ChatKit request')
        if isinstance(result,StreamingResult):
            return StreamingResponse(result,media_type='text/event-stream')
        return Response(content=result.json,media_type='application/json')

    return app
