import os
from pathlib import Path
from flask import Flask, session
from web.routes import register_routes
from web.services.security import (
    Tier,
    get_actual_tier,
    get_current_user,
    get_effective_tier,
    has_tier,
)


def load_env_file():
    """Load key-value environment variables from .env if present."""
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = value


def create_app():
    load_env_file()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    app.secret_key = os.environ.get("RB48_SECRET_KEY") or os.urandom(32)

    @app.context_processor
    def inject_security_context():
        user = get_current_user()
        return {
            "current_user": user,
            "effective_tier": get_effective_tier(),
            "actual_tier": get_actual_tier(user),
            "Tier": Tier,
            "has_tier": has_tier,
            "simulated_tier": session.get("simulated_tier") if user and user.get("role") == "webmaster" else None,
        }

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)