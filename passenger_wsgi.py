import sys
import os
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

try:
    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()
except Exception:
    error_html = """<html><body style="font-family:monospace;background:#1a1a1a;color:#f00;padding:20px">
    <h2>Django Startup Error</h2><pre style="color:#ff9;background:#111;padding:15px">{}</pre>
    <h3 style="color:#aaa">Python: {}</h3>
    <h3 style="color:#aaa">sys.path: {}</h3>
    <h3 style="color:#aaa">ENV vars present: SECRET_KEY={}, DB_NAME={}</h3>
    </body></html>""".format(
        traceback.format_exc(),
        sys.version,
        "<br>".join(sys.path),
        bool(os.environ.get('SECRET_KEY')),
        os.environ.get('DB_NAME', 'NOT SET')
    )
    def application(environ, start_response):
        start_response('500 Internal Server Error',
                       [('Content-Type', 'text/html; charset=utf-8')])
        return [error_html.encode('utf-8')]
