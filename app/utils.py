from app.extensions import db
from app.models import Sesion, Ticket

def sesion_activa():
    return Sesion.query.filter_by(activa=True).order_by(Sesion.iniciada_en.desc()).first()

def proximo_numero(sesion):
    """Devuelve el siguiente número de turno dentro de la sesión dada."""
    ultimo = db.session.query(db.func.max(Ticket.numero))\
                       .filter(Ticket.sesion_id == sesion.id).scalar()
    return (ultimo or 0) + 1

def tickets_de_sesion(sesion):
    return Ticket.query.filter_by(sesion_id=sesion.id).order_by(Ticket.numero.asc()).all()
