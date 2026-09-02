"""Flask application factory and global template context configuration."""

import os
from flask import Flask, session
from web.routes import register_routes
from web.services.security import (
    Tier,
    get_actual_tier,
    get_current_user,
    get_effective_tier,
    has_tier,
)


def create_app():
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