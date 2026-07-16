import logging
import os
import subprocess
import tempfile
import threading


LOG = logging.getLogger(__name__)


class TTSAdapter(object):
    def __init__(self, config, simulation=False):
        self.config = config
        self.simulation = simulation
        self._lock = threading.Lock()

    def speak(self, text):
        if not self.config.get("enabled", True):
            return
        thread = threading.Thread(target=self._speak, args=(text,), name="tts")
        thread.daemon = True
        thread.start()

    def _speak(self, text):
        if not self._lock.acquire(False):
            return
        output_path = None
        try:
            if self.simulation:
                LOG.info("TTS: %s", text)
                return
            model = self.config.get("model")
            if not model or not os.path.exists(model):
                raise RuntimeError("Piper Korean voice model is missing: %s" % model)
            handle = tempfile.NamedTemporaryFile(prefix="knu-rc-", suffix=".wav", delete=False)
            output_path = handle.name
            handle.close()
            command = [self.config.get("piper_command", "piper"), "--model", model,
                       "--output_file", output_path]
            config_path = self.config.get("config")
            if config_path and os.path.exists(config_path):
                command.extend(["--config", config_path])
            process = subprocess.Popen(command, stdin=subprocess.PIPE)
            process.communicate((text + "\n").encode("utf-8"))
            if process.returncode != 0:
                raise RuntimeError("Piper exited with %s" % process.returncode)
            subprocess.check_call(["aplay", "-q", output_path])
        except Exception as exc:
            LOG.error("TTS failed: %s", exc)
        finally:
            if output_path and os.path.exists(output_path):
                os.unlink(output_path)
            self._lock.release()
