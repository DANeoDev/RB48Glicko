import os
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, session  # noqa: E402
from web.routes import register_routes  # noqa: E402
from web.services.translations import (  # noqa: E402
    format_date_localized,
    get_current_lang,
    t,
)
from web.services.security import (  # noqa: E402
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
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
    app.secret_key = os.environ.get("RB48_SECRET_KEY") or os.urandom(32)

    @app.context_processor
    def inject_template_context():
        user = get_current_user()
        lang = get_current_lang()

        unseen_achievements_count = session.get("unseen_achievements_count", 0)
        if user and user.get("player_id") and "unseen_achievements_count" not in session:
            try:
                from scripts.analysis.achievements import get_user_unseen_achievements_count
                unseen_achievements_count = get_user_unseen_achievements_count(user["id"], user["player_id"])
                session["unseen_achievements_count"] = unseen_achievements_count
            except Exception:
                unseen_achievements_count = 0

        unseen_webmaster_notifications_count = 0
        if user and user.get("role") == "webmaster":
            try:
                from scripts.accounts.database import get_accounts_connection, get_unseen_webmaster_notifications_count
                acc_conn = get_accounts_connection()
                try:
                    unseen_webmaster_notifications_count = get_unseen_webmaster_notifications_count(acc_conn, user["id"])
                finally:
                    acc_conn.close()
            except Exception:
                unseen_webmaster_notifications_count = 0

        return {
            "current_user": user,
            "effective_tier": get_effective_tier(),
            "actual_tier": get_actual_tier(user),
            "Tier": Tier,
            "has_tier": has_tier,
            "is_webmaster": has_tier(Tier.WEBMASTER),
            "is_admin": has_tier(Tier.ADMIN),
            "simulated_tier": session.get("simulated_tier") if user and user.get("role") == "webmaster" else None,
            "current_lang": lang,
            "t": t,
            "get_current_lang": get_current_lang,
            "format_date_localized": format_date_localized,
            "unseen_achievements_count": unseen_achievements_count,
            "unseen_webmaster_notifications_count": unseen_webmaster_notifications_count,
        }

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
    app.run(debug=debug_mode)
