import functools
import hmac
import os
import time

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for


def create_app(service, config):
    app = Flask(__name__)
    app.secret_key = os.environ.get(config["secret_key_env"], "simulation-secret-change-me")
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
    username = os.environ.get(config["user_env"], "admin")
    password = os.environ.get(config["password_env"], "change-me")

    def authenticated(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not session.get("authenticated"):
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "authentication required"}), 401
                return redirect(url_for("login"))
            return func(*args, **kwargs)
        return wrapper

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            valid_user = hmac.compare_digest(request.form.get("username", ""), username)
            valid_password = hmac.compare_digest(request.form.get("password", ""), password)
            if valid_user and valid_password:
                session.clear()
                session["authenticated"] = True
                return redirect(url_for("index"))
            error = "아이디 또는 비밀번호가 올바르지 않습니다."
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    @authenticated
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @authenticated
    def index():
        return render_template("dashboard.html")

    @app.route("/video.mjpg")
    @authenticated
    def video():
        def stream():
            delay = 1.0 / float(config.get("stream_fps", 15))
            while True:
                frame = service.jpeg()
                if frame:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
                time.sleep(delay)
        return Response(stream(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/api/status")
    @authenticated
    def status():
        return jsonify(service.status())

    @app.route("/api/lidar")
    @authenticated
    def lidar():
        return jsonify({"points": service.lidar_points()})

    def action(callback):
        try:
            callback()
            return jsonify({"ok": True, "status": service.status()})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409

    @app.route("/api/control/start", methods=["POST"])
    @authenticated
    def start_follow():
        return action(service.request_follow)

    @app.route("/api/control/stop", methods=["POST"])
    @authenticated
    def stop_follow():
        return action(service.stop_follow)

    @app.route("/api/control/emergency", methods=["POST"])
    @authenticated
    def emergency():
        return action(service.emergency_stop)

    @app.route("/api/control/reset", methods=["POST"])
    @authenticated
    def reset():
        return action(service.reset_emergency)

    @app.route("/api/control/manual/<command>", methods=["POST"])
    @authenticated
    def manual(command):
        return action(lambda: service.manual(command))

    @app.route("/api/control/speed", methods=["POST"])
    @authenticated
    def speed():
        payload = request.get_json(silent=True) or {}
        return action(lambda: service.set_speed_limit(payload.get("speed")))

    @app.route("/api/control/camera/tilt", methods=["POST"])
    @authenticated
    def camera_tilt():
        payload = request.get_json(silent=True) or {}
        return action(lambda: service.set_camera_tilt(payload.get("tilt")))

    return app
