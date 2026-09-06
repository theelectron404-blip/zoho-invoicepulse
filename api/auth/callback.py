from http.server import BaseHTTPRequestHandler
import urllib.parse

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Extract code or error from query string
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        code = params.get('code', [None])[0]
        error = params.get('error', [None])[0]

        # Redirect back to the frontend homepage with code or error in URL query
        if code:
            redirect_url = f"/?code={urllib.parse.quote(code)}"
        elif error:
            redirect_url = f"/?error={urllib.parse.quote(error)}"
        else:
            redirect_url = "/"

        self.send_response(302)
        self.send_header('Location', redirect_url)
        self.end_headers()
