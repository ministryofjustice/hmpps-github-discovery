import http.server
import socketserver


class HealthHttpRequestHandler(http.server.SimpleHTTPRequestHandler):
  def do_GET(self):
    self.send_response(200)
    self.send_header('Content-type', 'text/plain')
    self.end_headers()
    self.wfile.write(bytes('UP', 'utf8'))
    return


class HealthServer:
  def __init__(self, host='', port=8080):
    self.host = host
    self.port = port

  def start(self):
    handler_object = HealthHttpRequestHandler
    with socketserver.TCPServer((self.host, self.port), handler_object) as httpd:
      print(f'Serving on {self.host}:{self.port}')
      httpd.serve_forever()
