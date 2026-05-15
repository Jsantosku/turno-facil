from flask import Blueprint, request, redirect, url_for, render_template, jsonify
from datetime import datetime
from app.extensions import db
from app.models import Ticket
from app.utils import sesion_activa, proximo_numero

client_bp = Blueprint('client', __name__)

@client_bp.route('/', methods=['GET'])
def cliente_index():
    s = sesion_activa()
    ticket_id = request.args.get('ticket_id', type=int)
    ticket = posicion = None
    if ticket_id and s:
        ticket = db.session.get(Ticket, ticket_id)
        if ticket and ticket.sesion_id == s.id:
            posicion = Ticket.query.filter(
                Ticket.sesion_id == s.id,
                Ticket.estado == 'waiting',
                Ticket.numero < ticket.numero
            ).count() + 1
    cola = []
    if s:
        cola = Ticket.query.filter(
            Ticket.sesion_id == s.id,
            Ticket.estado.in_(['waiting', 'called'])
        ).order_by(Ticket.numero.asc()).limit(20).all()
    return render_template('cliente.html',
        ticket=ticket, posicion=posicion, cola=cola,
        sesion_abierta=bool(s), now=datetime.utcnow())


@client_bp.route('/tomar_turno', methods=['POST'])
def tomar_turno():
    s = sesion_activa()
    if not s:
        return redirect(url_for('client.cliente_index'))
    # Registro del turno con sesion_id explícito
    nuevo = Ticket(
        sesion_id=s.id,
        numero=proximo_numero(s),
        estado='waiting'
    )
    db.session.add(nuevo)
    db.session.commit()
    return redirect(url_for('client.cliente_index', ticket_id=nuevo.id))
