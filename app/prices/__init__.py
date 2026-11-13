from flask import Blueprint

prices_bp = Blueprint('prices', __name__, url_prefix='/prices')

from app.prices import routes  # noqa: E402,F401
