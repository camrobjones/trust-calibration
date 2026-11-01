from django.urls import re_path

# WebSocket URL patterns will be populated once consumers are implemented.
# Stub provided to satisfy imports during initial Channels integration.

# Routing for WebSocket connections used by the conversation app.

from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/lobby/$", consumers.LobbyConsumer.as_asgi(), name="ws_lobby"),
    re_path(
        r"^ws/conversation/(?P<conv_id>\d+)/$",
        consumers.ChatConsumer.as_asgi(),
        name="ws_conversation",
    ),
]
