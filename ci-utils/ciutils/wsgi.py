import os  # Needed to set Django settings module in the process environment.

from django.core.wsgi import get_wsgi_application  # Factory that builds the WSGI callable.

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ciutils.settings")  # Point Django at our settings module.
application = get_wsgi_application()  # Gunicorn/uWSGI import this object as the app entry.
