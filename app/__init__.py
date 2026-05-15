from flask import Flask, jsonify
from config import Config
from app.extensions import db

def create_app(config_class=Config):
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(config_class)

    # Initialize Flask extensions
    db.init_app(app)

    # Register blueprints
    from app.routes_client import client_bp
    from app.routes_emp import emp_bp

    app.register_blueprint(client_bp)
    app.register_blueprint(emp_bp)

    # API Route (from original code)
    @app.route('/api/estado')
    def api_estado():
        from app.models import Ticket
        from app.utils import sesion_activa
        s = sesion_activa()
        q = Ticket.query.filter(Ticket.sesion_id == s.id) if s else Ticket.query.filter(False)
        return jsonify({
            'jornada_activa': bool(s),
            'sesion_id':      s.id if s else None,
            'waiting': q.filter(Ticket.estado == 'waiting').count(),
            'called':  q.filter(Ticket.estado == 'called').count(),
            'served':  q.filter(Ticket.estado == 'served').count(),
            'missed':  q.filter(Ticket.estado == 'missed').count(),
        })

    return app
