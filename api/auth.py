from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            req = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "Invalid JSON"}')
            return

        action = req.get('action')
        client_id = req.get('client_id')
        client_secret = req.get('client_secret')
        accounts_domain = req.get('accounts_domain', 'https://accounts.zoho.com')

        token_url = f"{accounts_domain}/oauth/v2/token"

        if action == 'exchange':
            payload = {
                'code': req.get('code'),
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': req.get('redirect_uri'),
                'grant_type': 'authorization_code',
            }
        elif action == 'refresh':
            payload = {
                'refresh_token': req.get('refresh_token'),
                'client_id': client_id,
                'client_secret': client_secret,
                'grant_type': 'refresh_token',
            }
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "Invalid action"}')
            return

        data = urllib.parse.urlencode(payload).encode('utf-8')
        req_post = urllib.request.Request(token_url, data=data, method='POST')
        req_post.add_header('Content-Type', 'application/x-www-form-urlencoded')

        try:
            with urllib.request.urlopen(req_post) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
