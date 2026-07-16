import logging
import threading


LOG = logging.getLogger(__name__)


class VehicleAdapter(object):
    def __init__(self, simulation=False):
        self.simulation = simulation
        self.car = None
        self.speed = 0
        self.steering = 0.0
        self.pan = 90.0
        self.tilt = 45.0
        self._lock = threading.RLock()

    def start(self):
        if not self.simulation:
            from pop import Pilot
            self.car = Pilot.AutoCar()
        self.stop()

    def drive(self, speed, steering=0.0):
        with self._lock:
            speed = int(max(-99, min(99, speed)))
            steering = float(max(-1.0, min(1.0, steering)))
            self.speed, self.steering = speed, steering
            if self.simulation:
                return
            self.car.steering = steering
            if speed > 0:
                self.car.forward(speed)
            elif speed < 0:
                self.car.backward(abs(speed))
            else:
                self.car.stop()

    def stop(self):
        with self._lock:
            self.speed, self.steering = 0, 0.0
            if self.car is not None:
                self.car.stop()
                self.car.steering = 0

    def pan_tilt(self, pan, tilt):
        with self._lock:
            self.pan = float(max(0, min(180, pan)))
            self.tilt = float(max(-30, min(200, tilt)))
            if self.car is not None:
                self.car.camPan(int(round(self.pan)))
                self.car.camTilt(int(round(self.tilt)))

    def close(self):
        self.stop()
