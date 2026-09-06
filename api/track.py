from http.server import BaseHTTPRequestHandler

# 43-byte transparent GIF
GIF_1X1 = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01"
    b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Return 1x1 transparent GIF with anti-caching headers
        self.send_response(200)
        self.send_header('Content-Type', 'image/gif')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(GIF_1X1)
