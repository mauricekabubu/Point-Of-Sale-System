from http.server import BaseHTTPRequestHandler, HTTPServer



class MyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        html = b"""
        <html>
        <head><title>Test Page</title></head>
        <body><h1>Hello from Python HTTP Server!</h1></body>
        </html>
        """
        self.wfile.write(html)

def run(server_class=HTTPServer, handler_class=MyHandler, port=8080):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"Serving custom HTML at http://localhost:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    run()