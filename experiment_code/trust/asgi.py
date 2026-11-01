"""
ASGI config for trust project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# Channels
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import conversation.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trust.settings")

# Build standard Django ASGI application first
django_asgi_app = get_asgi_application()

# Expose ProtocolTypeRouter that routes HTTP and WebSocket connections
application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(conversation.routing.websocket_urlpatterns)
        ),
    }
)
