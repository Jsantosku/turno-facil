from flask import Blueprint, request, redirect, url_for, render_template, jsonify, Response
from datetime import datetime
from app.extensions import db
from app.models import Sesion, Ticket
from app.utils import sesion_activa, tickets_de_sesion
from app.pdf_report import _generar_pdf

emp_bp = Blueprint('empleado', __name__, url_prefix='/empleado')

@emp_bp.route('/')
def empleado_index():
    s = sesion_activa()
    ultimo_llamado = hora_inicio = None
    if s:
        ultimo_llamado = Ticket.query.filter(
            Ticket.sesion_id == s.id,
            Ticket.estado == 'called'
        ).order_by(Ticket.llamado_en.desc()).first()
        hora_inicio = s.iniciada_en.strftime('%H:%M')
    return render_template('empleado.html',
        actual_numero=ultimo_llamado.numero if ultimo_llamado else None,
        sesion_abierta=bool(s), hora_inicio=hora_inicio)


@emp_bp.route('/iniciar_jornada')
def iniciar_jornada():
    Sesion.query.filter_by(activa=True).update(
        {'activa': False, 'cerrada_en': datetime.utcnow()}
    )
    nueva = Sesion()
    db.session.add(nueva)
    db.session.commit()
    return redirect(url_for('empleado.empleado_index'))


@emp_bp.route('/terminar_jornada')
def terminar_jornada():
    s = sesion_activa()
    if s:
        Ticket.query.filter(
            Ticket.sesion_id == s.id,
            Ticket.estado.in_(['waiting', 'called'])
        ).update({'estado': 'missed', 'atendido_en': datetime.utcnow()},
                 synchronize_session=False)
        s.activa = False
        s.cerrada_en = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('empleado.empleado_index'))


@emp_bp.route('/cola_json')
def empleado_cola_json():
    s = sesion_activa()
    if not s:
        return jsonify([])
    cola = Ticket.query.filter(
        Ticket.sesion_id == s.id,
        Ticket.estado.in_(['waiting', 'called'])
    ).order_by(Ticket.numero.asc()).limit(50).all()
    return jsonify([{'id': t.id, 'numero': t.numero, 'estado': t.estado} for t in cola])


@emp_bp.route('/llamar_siguiente', methods=['POST'])
def empleado_llamar_siguiente():
    s = sesion_activa()
    if not s:
        return jsonify({'error': 'No hay jornada activa.'})
    sig = Ticket.query.filter(
        Ticket.sesion_id == s.id,
        Ticket.estado == 'waiting'
    ).order_by(Ticket.numero.asc()).with_for_update().first()
    if not sig:
        return jsonify({'error': 'No hay turnos en espera.'})
    sig.estado = 'called'
    sig.llamado_en = datetime.utcnow()
    db.session.commit()
    return jsonify({'numero': sig.numero})


@emp_bp.route('/llamar_especifico', methods=['POST'])
def empleado_llamar_especifico():
    s = sesion_activa()
    if not s:
        return jsonify({'error': 'No hay jornada activa.'})
    data = request.get_json() or {}
    numero = data.get('numero')
    if numero is None:
        return jsonify({'error': 'Falta número.'})
    t = Ticket.query.filter(
        Ticket.sesion_id == s.id,
        Ticket.numero == numero
    ).first()
    if not t:
        return jsonify({'error': f'No existe el turno {numero} en esta jornada.'})
    t.estado = 'called'
    t.llamado_en = datetime.utcnow()
    db.session.commit()
    return jsonify({'numero': t.numero})


@emp_bp.route('/servir_actual')
def empleado_servir_actual():
    s = sesion_activa()
    if not s:
        return redirect(url_for('empleado.empleado_index'))
    t = Ticket.query.filter(
        Ticket.sesion_id == s.id,
        Ticket.estado == 'called'
    ).order_by(Ticket.llamado_en.desc()).first()
    if t:
        t.estado = 'served'
        t.atendido_en = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('empleado.empleado_index'))


@emp_bp.route('/marcar_perdido', methods=['POST'])
def empleado_marcar_perdido():
    s = sesion_activa()
    if not s:
        return jsonify({'error': 'No hay jornada activa.'})
    t = Ticket.query.filter(
        Ticket.sesion_id == s.id,
        Ticket.estado == 'called'
    ).order_by(Ticket.llamado_en.desc()).first()
    if not t:
        return jsonify({'error': 'No hay turno llamado para marcar como perdido.'})
    t.estado = 'missed'
    t.atendido_en = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})


@emp_bp.route('/reporte_hoy_json')
def empleado_reporte_hoy_json():
    s = sesion_activa()
    if not s:
        s = Sesion.query.filter_by(activa=False)\
                        .order_by(Sesion.cerrada_en.desc()).first()
    if not s:
        return jsonify({'total': 0, 'atendidos': 0, 'perdidos': 0, 'en_espera': 0, 'todos': []})
    tickets = tickets_de_sesion(s)
    def fmt(dt): return dt.strftime('%H:%M:%S') if dt else None
    return jsonify({
        'total':     len(tickets),
        'atendidos': sum(1 for t in tickets if t.estado == 'served'),
        'perdidos':  sum(1 for t in tickets if t.estado == 'missed'),
        'en_espera': sum(1 for t in tickets if t.estado in ('waiting', 'called')),
        'todos': [{'numero': t.numero, 'estado': t.estado,
                   'llamado_en': fmt(t.llamado_en), 'atendido_en': fmt(t.atendido_en)}
                  for t in tickets]
    })


@emp_bp.route('/descargar_reporte')
def descargar_reporte():
    s = sesion_activa()
    if not s:
        s = Sesion.query.filter_by(activa=False)\
                        .order_by(Sesion.cerrada_en.desc()).first()
    if not s:
        return 'No hay jornada registrada.', 404

    pdf_bytes = _generar_pdf(s)
    nombre = f"reporte_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{nombre}"'}
    )
