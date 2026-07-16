import logging
import os
import signal
import sys

from autocar.config import load_config
from autocar.service import AutoCarService
from autocar.web.app import create_app


def main():
    config = load_config()
    os.makedirs("logs", exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers = [logging.StreamHandler(), logging.FileHandler("logs/autocar.log")]
    for handler in handlers:
        handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(getattr(logging, config["runtime"].get("log_level", "INFO")))
    root.handlers = handlers
    if not config["runtime"].get("simulation", False):
        missing = [name for name in (config["web"]["secret_key_env"], config["web"]["user_env"],
                                     config["web"]["password_env"]) if not os.environ.get(name)]
        if missing:
            raise RuntimeError("required production environment variables missing: %s" % ", ".join(missing))
    service = AutoCarService(config)
    service.start()

    def shutdown(signum, frame):
        logging.getLogger(__name__).info("signal %s received; stopping vehicle", signum)
        service.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    app = create_app(service, config["web"])
    try:
        from waitress import serve
        serve(app, host=config["web"]["host"], port=int(config["web"]["port"]), threads=6)
    finally:
        service.shutdown()


if __name__ == "__main__":
    main()
