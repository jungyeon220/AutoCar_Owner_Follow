import logging
import threading
import time


LOG = logging.getLogger(__name__)


class BluetoothMonitor(object):
    def __init__(self, config, simulation=False):
        self.config = config
        self.simulation = simulation
        self.connected = simulation or not config.get("enabled", False)
        self.running = False
        self._thread = None
        self._dbus = None
        self._bus = None
        self._device_path = None

    def start(self):
        if not self.config.get("enabled", False):
            self.connected = True
            return
        if not self.config.get("owner_mac"):
            raise ValueError("bluetooth.owner_mac is required when Bluetooth authentication is enabled")
        self.running = True
        self._thread = threading.Thread(target=self._run, name="bluetooth-monitor")
        self._thread.daemon = True
        self._thread.start()

    def _run(self):
        while self.running:
            try:
                if self._bus is None:
                    import dbus
                    self._dbus = dbus
                    self._bus = dbus.SystemBus()
                self.connected = self._read_connected()
            except Exception as exc:
                LOG.warning("Bluetooth status failed: %s", exc)
                self.connected = False
                self._device_path = None
            time.sleep(float(self.config.get("poll_seconds", 1.0)))

    def _find_device_path(self):
        manager = self._dbus.Interface(
            self._bus.get_object("org.bluez", "/"),
            "org.freedesktop.DBus.ObjectManager")
        owner_mac = self.config["owner_mac"].upper()
        for path, interfaces in manager.GetManagedObjects().items():
            device = interfaces.get("org.bluez.Device1")
            if device and str(device.get("Address", "")).upper() == owner_mac:
                return path
        return None

    def _read_connected(self):
        if self._device_path is None:
            self._device_path = self._find_device_path()
        if self._device_path is None:
            return False
        properties = self._dbus.Interface(
            self._bus.get_object("org.bluez", self._device_path),
            "org.freedesktop.DBus.Properties")
        return bool(properties.Get("org.bluez.Device1", "Connected"))

    def stop(self):
        self.running = False
