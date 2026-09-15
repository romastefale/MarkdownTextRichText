from aiohttp import web

from mdtxtrt.config import load_settings
from mdtxtrt.web.server import Server


def main() -> None:
    settings = load_settings()
    web.run_app(Server(settings).app(), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
