"""Install cumulative AutoCAR v0.9.1 POP nearest-person update."""
import compileall
import datetime
import importlib
import json
import os
import shutil
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED


INSTALL_ROOT = os.environ.get("KNU_RC_ROOT", "/home/soda/Project/python/notebook")
UPDATE_ZIP = os.path.join(INSTALL_ROOT, "KNU_RC_DEVICE_POP_NEAREST_OWNER_v0.9.1.zip")
CONFIG_PATH = os.path.join(INSTALL_ROOT, "config", "autocar.json")
PATCH_NAME = "pop_nearest_owner_config_patch.json"
SOURCE_FILES = [
    "autocar/__init__.py", "autocar/config.py", "autocar/controller.py",
    "autocar/main.py", "autocar/models.py", "autocar/owner.py",
    "autocar/service.py", "autocar/state_machine.py", "autocar/wave.py",
    "autocar/adapters/__init__.py", "autocar/adapters/bluetooth.py",
    "autocar/adapters/camera.py", "autocar/adapters/cds.py",
    "autocar/adapters/lidar.py", "autocar/adapters/tts.py",
    "autocar/adapters/vehicle.py", "autocar/adapters/vision.py",
    "autocar/web/__init__.py", "autocar/web/app.py",
    "autocar/web/templates/dashboard.html", "autocar/web/templates/login.html",
    "autocar/web/static/dashboard.css", "autocar/web/static/dashboard.js",
]


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def running_autocar_pids():
    result = []
    if not os.path.isdir("/proc"):
        return result
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(os.path.join("/proc", name, "cmdline"), "rb") as handle:
                arguments = [part.decode("utf-8", "replace")
                             for part in handle.read().split(b"\0") if part]
            if "autocar.main" in arguments:
                result.append(int(name))
        except (OSError, IOError):
            pass
    return sorted(result)


def merge_selected(config, patch):
    for section in ("camera", "detector", "pose", "aruco", "selection",
                    "owner", "camera_tracking"):
        config.setdefault(section, {}).update(patch.get(section, {}))


def main():
    running = running_autocar_pids()
    if running:
        raise RuntimeError("stop AutoCAR before installation; running PIDs: %s" % running)
    if not os.path.isfile(UPDATE_ZIP):
        raise RuntimeError("update ZIP not found: %s" % UPDATE_ZIP)
    if not os.path.isfile(CONFIG_PATH):
        raise RuntimeError("device config not found: %s" % CONFIG_PATH)

    with ZipFile(UPDATE_ZIP, "r") as archive:
        patch = json.loads(archive.read(PATCH_NAME).decode("utf-8"))
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(INSTALL_ROOT, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, "before-nearest-owner-%s.zip" % stamp)
    with ZipFile(backup_path, "w", ZIP_DEFLATED) as backup:
        for relative in SOURCE_FILES + ["config/autocar.json"]:
            path = os.path.join(INSTALL_ROOT, *relative.split("/"))
            if os.path.isfile(path):
                backup.write(path, relative)

    temp_dir = tempfile.mkdtemp(prefix="nearest-owner-update-", dir=INSTALL_ROOT)
    try:
        with ZipFile(UPDATE_ZIP, "r") as archive:
            required = set(SOURCE_FILES + [PATCH_NAME])
            members = {name.replace("\\", "/").lstrip("./"): name
                       for name in archive.namelist()}
            missing = sorted(required - set(members))
            if missing:
                raise RuntimeError("update ZIP is missing: %s" % ", ".join(missing))
            for name in required:
                if name.startswith("/") or ".." in name.split("/"):
                    raise RuntimeError("unsafe ZIP path: %s" % name)
                target = os.path.join(temp_dir, *name.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(members[name], "r") as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)

        for relative in SOURCE_FILES:
            source = os.path.join(temp_dir, *relative.split("/"))
            target = os.path.join(INSTALL_ROOT, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)

        config = load_json(CONFIG_PATH)
        merge_selected(config, patch)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=os.path.dirname(CONFIG_PATH),
            prefix="autocar-", suffix=".json", delete=False)
        try:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.close()
            os.replace(handle.name, CONFIG_PATH)
        except Exception:
            handle.close()
            if os.path.exists(handle.name):
                os.unlink(handle.name)
            raise

        if not compileall.compile_dir(os.path.join(INSTALL_ROOT, "autocar"), quiet=1):
            raise RuntimeError("Python compilation failed; restore backup %s" % backup_path)
        sys.path.insert(0, INSTALL_ROOT)
        import autocar.config as config_module
        config_module = importlib.reload(config_module)
        checked = config_module.load_config(CONFIG_PATH)
        print("Installation complete: AutoCAR v0.9.1")
        print("Backup:", backup_path)
        print("Detector backend:", checked["detector"]["backend"])
        print("Authentication: registered Bluetooth + nearest visible person")
        print("Camera: %sx%s at %s FPS" %
              (checked["camera"]["width"], checked["camera"]["height"],
               checked["camera"]["fps"]))
        print("Inference: %sx%s" %
              (checked["camera"]["inference_width"],
               checked["camera"]["inference_height"]))
        print("Initial owner: tallest person box, locked after 3 of 5 detections")
        print("Registration: 20 clothing-pattern frames; standing still is allowed")
        print("Initial camera PAN/TILT: %.0f / %.0f degrees" %
              (checked["camera_tracking"]["pan_center"],
               checked["camera_tracking"]["tilt_center"]))
        print("Normal follow: clothing pattern; ArUco and Pose disabled")
        print("Owner loss: clothing search for %.1f seconds" %
              checked["owner"]["search_seconds"])
        print("Search failure: stop in IDLE until dashboard Follow is pressed again")
        print("Dashboard camera TILT control: %.0f to %.0f degrees" %
              (checked["camera_tracking"]["tilt_min"],
               checked["camera_tracking"]["tilt_max"]))
        print("Pose runtime: disabled")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
