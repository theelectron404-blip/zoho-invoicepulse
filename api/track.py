from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import os
import time

# 43-byte transparent GIF
GIF_1X1 = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01"
    b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)

# In-memory tracking store for open events
TRACK_EVENTS = {}

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # 1. Status query endpoint (for frontend to poll real-time opens)
        if 'status' in params or 'events' in params:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(json.dumps({'events': TRACK_EVENTS}).encode('utf-8'))
            return

        # 2. Open tracking beacon hit (from recipient mail client)
        inv_id = params.get('id', [None])[0]
        email = params.get('email', [None])[0]

        if inv_id or email:
            key = (inv_id or email).lower()
            if key not in TRACK_EVENTS:
                TRACK_EVENTS[key] = {'opens': 0, 'last_opened': 0, 'email': email, 'inv': inv_id}
            TRACK_EVENTS[key]['opens'] += 1
            TRACK_EVENTS[key]['last_opened'] = int(time.time())

        # Return 1x1 transparent GIF with anti-caching headers so email clients always load it
        self.send_response(200)
        self.send_header('Content-Type', 'image/gif')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0, post-check=0, pre-check=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', 'Thu, 01 Jan 1970 00:00:00 GMT')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(GIF_1X1)

