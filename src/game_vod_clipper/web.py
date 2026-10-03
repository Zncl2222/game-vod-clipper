"""Local web server entry point. Run one Uvicorn process bound to loopback."""
import os

import uvicorn

from .api.app import create_app as create_app
from .api.server import LocalServer


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Local BossCut POC (one server process)"
    )
    parser.add_argument("--port", type=int, default=8000)
    # Containers need 0.0.0.0 so a published Docker port can reach the server.
    parser.add_argument("--host", default=os.environ.get("GAME_VOD_HOST", "127.0.0.1"))
    args = parser.parse_args()
    app = create_app()
    config = uvicorn.Config(app, host=args.host, port=args.port,
                            timeout_graceful_shutdown=5)
    try:
        LocalServer(config, app.state.shutting_down).run()
    except KeyboardInterrupt:
        # Match uvicorn.run(): signal handling and cleanup already ran.
        pass
