import threading


VALID_TRANSITIONS = {
    "INIT": ("IDLE", "EMERGENCY"),
    "IDLE": ("SELECT_NEAREST_OWNER", "MANUAL", "EMERGENCY"),
    "SELECT_NEAREST_OWNER": ("REGISTER_OWNER", "FOLLOW_OWNER", "IDLE", "EMERGENCY"),
    "REGISTER_OWNER": ("FOLLOW_OWNER", "SELECT_NEAREST_OWNER", "IDLE", "EMERGENCY"),
    "FOLLOW_OWNER": ("SEARCH_OWNER", "BLOCKED", "REAUTHENTICATION", "IDLE", "EMERGENCY"),
    "SEARCH_OWNER": ("FOLLOW_OWNER", "BLOCKED", "REAUTHENTICATION", "IDLE", "EMERGENCY"),
    "BLOCKED": ("FOLLOW_OWNER", "SEARCH_OWNER", "IDLE", "EMERGENCY"),
    "REAUTHENTICATION": ("SELECT_NEAREST_OWNER", "IDLE", "EMERGENCY"),
    "MANUAL": ("IDLE", "EMERGENCY"),
    "EMERGENCY": ("IDLE",)
}


class StateMachine(object):
    def __init__(self):
        self.state = "INIT"
        self.reason = "starting"
        self._lock = threading.RLock()

    def transition(self, new_state, reason):
        with self._lock:
            if new_state == self.state:
                self.reason = reason
                return
            if new_state not in VALID_TRANSITIONS.get(self.state, ()):
                raise ValueError("invalid transition %s -> %s" % (self.state, new_state))
            self.state = new_state
            self.reason = reason

    def force_emergency(self, reason):
        with self._lock:
            self.state = "EMERGENCY"
            self.reason = reason
