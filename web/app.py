import os
from flask import Flask, session
from scripts.accounts.auth import get_user
from web.routes import register_routes


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    app.secret_key = os.environ.get("RB48_SECRET_KEY") or os.urandom(32)

    @app.context_processor
    def inject_current_user():
        user_id = session.get("user_id")
        return {"current_user": get_user(user_id) if user_id else None}

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)