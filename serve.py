"""Local viewer only; Python standard library, fixed native executable, loopback bind."""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'python'))
from packer_adapter.validation import validate
from packer_adapter.validation_3d import loads as strict_loads
EXE = pathlib.Path(os.environ.get('PACKER_BINARY',str(ROOT / 'build' / ('packer.exe' if sys.platform == 'win32' else 'packer'))))
LIMIT = 1048576
VALIDATE_LIMIT = 4 * LIMIT
SLOTS = threading.BoundedSemaphore(2)

def solve(payload):
    if len(payload) > LIMIT:
        return 413, {'error':'Request exceeds 1 MiB.'}
    try:
        p = subprocess.run([str(EXE)], input=payload, capture_output=True, timeout=65)
        result = json.loads(p.stdout)
        return (200 if p.returncode == 0 else 400), result
    except FileNotFoundError:
        return 503, {'error':'Build the solver before using the viewer: build.ps1 or build.sh.'}
    except subprocess.TimeoutExpired:
        return 504, {'error':'Solver process timed out.'}
    except (ValueError, OSError):
        return 500, {'error':'Invalid solver response.'}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT/'viewer'), **kwargs)
    def send_json(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        if self.path not in ('/api/pack', '/api/validate'):
            self.send_json(404,{'error':'Unknown endpoint'});return
        origin=self.headers.get('Origin')
        if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
            self.send_json(403,{'error':'Origin not allowed.'});return
        try: length=int(self.headers.get('Content-Length','-1'))
        except ValueError: length=-1
        if not 0<=length<=(LIMIT if self.path=='/api/pack' else VALIDATE_LIMIT):
            self.send_json(413,{'error':'Invalid request size.'});return
        if not SLOTS.acquire(blocking=False):
            self.send_json(429,{'error':'Solver busy. Try again.'});return
        try:
            self.connection.settimeout(10)
            payload=self.rfile.read(length)
            if self.path == '/api/pack':
                self.send_json(*solve(payload))
            else:
                try:
                    pair = strict_loads(payload.decode('utf-8'))
                    if type(pair) is not dict or set(pair) != {'request', 'result'}:
                        raise ValueError('Expected original request and result.')
                    errors = validate(pair['request'], pair['result'])
                    self.send_json(200, {'valid': not errors, 'errors': errors})
                except (ValueError, UnicodeError) as exc:
                    self.send_json(400, {'valid': False, 'errors': [str(exc)]})
        finally: SLOTS.release()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'paCker: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
