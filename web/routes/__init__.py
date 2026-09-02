from .auth import auth_bp
from .news import news_bp
from .stats import stats_bp
from .match_center import match_center_bp


def register_routes(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(match_center_bp)
