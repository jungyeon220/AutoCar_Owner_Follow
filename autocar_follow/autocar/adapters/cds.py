import logging
import time


LOG = logging.getLogger(__name__)


class CdsAdapter(object):
    """Rate-limited POP CDS sensor reader."""
    def __init__(self, config, simulation=False):
        self.config = config
        self.simulation = simulation
        self.sensor = None
        self.ok = False
        self.value = None
        self._last_read = 0.0

    def start(self):
        if not self.config.get("enabled", True):
            return
        if self.simulation:
            self.ok = True
            self.value = float(self.config.get("simulation_value", 512.0))
            return
        try:
            from pop import Cds
            self.sensor = Cds(int(self.config.get("channel", 7)))
            self.read(force=True)
        except Exception:
            self.ok = False
            LOG.exception("CDS sensor initialization failed")

    def read(self, force=False):
        if not self.config.get("enabled", True):
            return None
        if self.simulation:
            return self.value
        now = time.monotonic()
        interval = float(self.config.get("poll_seconds", 0.25))
        if not force and self._last_read and now - self._last_read < interval:
            return self.value
        self._last_read = now
        if self.sensor is None:
            self.ok = False
            return None
        try:
            self.value = float(self.sensor.read())
            self.ok = True
        except Exception as error:
            self.ok = False
            LOG.warning("CDS sensor read failed: %s", error)
        return self.value

    def stop(self):
        self.sensor = None
        self.ok = False
