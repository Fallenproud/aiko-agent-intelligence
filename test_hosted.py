import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import create_app

class HostedTests(unittest.TestCase):
    def test_secure_canonical_origin_and_configuration(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'AIKO_PUBLIC_BASE_URL':'https://aiko.example','AIKO_COOKIE_SECURE':'1','AIKO_CHATKIT_DOMAIN_KEY':'test-domain-key'}):
            app=create_app(Path(tmp)/'hosted.sqlite3',worker=False)
            app.state.auth.provision('operator','password-test-12345')
            with TestClient(app,base_url='https://aiko.example') as c:
                self.assertEqual(c.get('/healthz').json()['status'],'ok')
                r=c.post('/api/auth/login',json={'username':'operator','password':'password-test-12345'},headers={'Origin':'https://aiko.example'})
                self.assertEqual(r.status_code,200,r.text)
                self.assertIn('Secure',r.headers['set-cookie'])
                c.headers['X-CSRF-Token']=r.json()['csrf']
                self.assertEqual(c.get('/api/chatkit/config').json()['domain_key'],'test-domain-key')
                self.assertEqual(c.post('/api/runs',json={},headers={'Origin':'https://wrong.example'}).status_code,403)
                self.assertEqual(c.post('/api/runs',json={},headers={'Origin':'https://aiko.example'}).status_code,201)
                self.assertEqual(c.get('/healthz',headers={'Host':'wrong.example'}).status_code,400)
    def test_hosted_mode_fails_without_secure_cookies(self):
        with patch.dict(os.environ,{'AIKO_PUBLIC_BASE_URL':'https://aiko.example','AIKO_COOKIE_SECURE':'0'}):
            with self.assertRaises(ValueError):create_app(':memory:',worker=False)
