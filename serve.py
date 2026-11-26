"""Start the restoration service with a readiness route for the runner."""
import argparse

from releases.service import build_server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sound restoration HTTP service")
    parser.add_argument("--db", required=True)
    parser.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    with build_server(args.db, args.port) as server:
        handler = server.RequestHandlerClass

        class ReadinessHandler(handler):
            def do_GET(self):
                if self.path == "/ready":
                    self._reply(200, {"ready": True})
                else:
                    super().do_GET()

        server.RequestHandlerClass = ReadinessHandler
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
