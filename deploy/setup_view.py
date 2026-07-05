"""
One-time browser-triggered deployment setup view.
Access: https://nutri.pharn.org/deploy-setup/?secret=YOUR_SETUP_SECRET

IMPORTANT: Delete this file (and its URL entry in urls.py) after first use.
"""
import os
from django.http import HttpResponse
from django.core.management import call_command
from io import StringIO
from decouple import config


def run_setup(request):
    """
    Runs migrate, collectstatic, and creates the superuser.
    Protected by SETUP_SECRET env variable.
    """
    secret = config('SETUP_SECRET', default='')
    provided = request.GET.get('secret', '')

    if not secret or provided != secret:
        return HttpResponse(
            '<h2 style="color:red">403 — Invalid or missing setup secret.</h2>',
            status=403
        )

    output = StringIO()
    log = []

    # Run migrations
    try:
        call_command('migrate', '--noinput', stdout=output, stderr=output)
        log.append(f'<p style="color:green">✔ Migrations applied successfully.</p>')
        log.append(f'<pre>{output.getvalue()}</pre>')
    except Exception as e:
        log.append(f'<p style="color:red">✘ Migration error: {e}</p>')

    # Collect static files
    try:
        static_out = StringIO()
        call_command('collectstatic', '--noinput', stdout=static_out, stderr=static_out)
        log.append(f'<p style="color:green">✔ Static files collected.</p>')
    except Exception as e:
        log.append(f'<p style="color:orange">⚠ Collectstatic warning: {e}</p>')

    # Create superuser
    try:
        from apps.users.models import User
        admin_email = 'admin@cmam.com'
        admin_pass = config('ADMIN_PASSWORD', default='Admin@2026!')
        if not User.objects.filter(email=admin_email).exists():
            User.objects.create_superuser(admin_email, admin_pass, name='Administrator')
            log.append(
                f'<p style="color:green">✔ Superuser created: '
                f'<strong>{admin_email}</strong> / '
                f'<strong>{admin_pass}</strong></p>'
            )
        else:
            log.append(f'<p style="color:blue">ℹ Superuser already exists: {admin_email}</p>')
    except Exception as e:
        log.append(f'<p style="color:red">✘ Superuser error: {e}</p>')

    html = """
    <html>
    <head><title>CMAM Tracker — Deployment Setup</title>
    <style>body{{font-family:sans-serif;max-width:800px;margin:40px auto;padding:0 20px}}
    pre{{background:#f4f4f4;padding:12px;overflow-x:auto;font-size:12px}}</style>
    </head>
    <body>
    <h2>CMAM Tracker — Deployment Setup</h2>
    {content}
    <hr>
    <p style="color:red"><strong>⚠ IMPORTANT:</strong> Now that setup is complete,
    remove <code>deploy/setup_view.py</code> and its URL from
    <code>config/urls.py</code>, then restart the app.</p>
    </body></html>
    """.format(content=''.join(log))

    return HttpResponse(html)
