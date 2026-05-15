# app_turnos.py
from flask import Flask, request, redirect, url_for, render_template_string, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import io
import os

# ── ReportLab (PDF) ────────────────────────────────────────────
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///turnos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ══════════════════════════════════════════════════════════════
#  MODELOS
# ══════════════════════════════════════════════════════════════

class Sesion(db.Model):
    """Registra cada jornada de trabajo (apertura / cierre).
    Al iniciar una nueva jornada, el contador de turnos vuelve a 1."""
    __tablename__ = 'sesion'

    id          = db.Column(db.Integer, primary_key=True)
    iniciada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                            comment='Momento en que el empleado inició la jornada')
    cerrada_en  = db.Column(db.DateTime, nullable=True,  default=None,
                            comment='Momento en que la jornada fue cerrada (NULL = aún activa)')
    activa      = db.Column(db.Boolean,  nullable=False, default=True,
                            comment='True = jornada en curso, False = cerrada')

    # Relación inversa para acceder a los tickets de la jornada
    tickets = db.relationship('Ticket', back_populates='sesion',
                              cascade='all, delete-orphan', lazy='dynamic')


class Ticket(db.Model):
    """Un registro por cada turno generado.
    El campo `numero` se reinicia en cada jornada (sesion_id).

    Estados:
      waiting → en la cola esperando ser llamado
      called  → ya fue llamado por el empleado, aún no atendido
      served  → atendido y cerrado correctamente
      missed  → cliente no se presentó / turno cancelado
    """
    __tablename__ = 'ticket'

    id          = db.Column(db.Integer, primary_key=True,
                            comment='PK interna')
    sesion_id   = db.Column(db.Integer, db.ForeignKey('sesion.id', ondelete='CASCADE'),
                            nullable=False, index=True,
                            comment='Jornada a la que pertenece este turno')
    numero      = db.Column(db.Integer, nullable=False, index=True,
                            comment='Número visible para el cliente (1, 2, 3… por jornada)')
    estado      = db.Column(db.String(20), nullable=False, default='waiting',
                            comment='Estado actual del turno')
    creado      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                            comment='Momento en que el cliente tomó el turno')
    llamado_en  = db.Column(db.DateTime, nullable=True,
                            comment='Momento en que el empleado lo llamó')
    atendido_en = db.Column(db.DateTime, nullable=True,
                            comment='Momento en que fue marcado como atendido o perdido')

    # Relación hacia la sesión
    sesion = db.relationship('Sesion', back_populates='tickets')

    __table_args__ = (
        db.UniqueConstraint('sesion_id', 'numero', name='uq_ticket_sesion_numero'),
    )


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def sesion_activa():
    return Sesion.query.filter_by(activa=True).order_by(Sesion.iniciada_en.desc()).first()


def proximo_numero(sesion):
    """Devuelve el siguiente número de turno dentro de la sesión dada."""
    ultimo = db.session.query(db.func.max(Ticket.numero))\
                       .filter(Ticket.sesion_id == sesion.id).scalar()
    return (ultimo or 0) + 1


def tickets_de_sesion(sesion):
    return Ticket.query.filter_by(sesion_id=sesion.id).order_by(Ticket.numero.asc()).all()


# ══════════════════════════════════════════════════════════════
#  TEMPLATE CLIENTE
# ══════════════════════════════════════════════════════════════

TEMPLATE_CLIENTE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Papelería Espacios — Turnos</title>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
  <style>
    :root { --ink:#1a1209; --paper:#fdf8ef; --cream:#f5ead6; --rust:#c0440a; --gold:#d4940a; --sage:#4a7c59; --mid:#8c7a60; }
    *, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
    body { font-family:'DM Sans',sans-serif; background:var(--paper); color:var(--ink); min-height:100vh; }
    body::before {
      content:''; position:fixed; inset:0;
      background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
      pointer-events:none; z-index:999;
    }
    header { background:var(--ink); color:var(--paper); padding:1.5rem 2rem; display:flex; align-items:center; gap:1.5rem; border-bottom:4px solid var(--rust); }
    .logo-mark { width:52px; height:52px; background:var(--rust); border-radius:4px; display:flex; align-items:center; justify-content:center; font-family:'Playfair Display',serif; font-size:1.6rem; font-weight:900; color:var(--paper); flex-shrink:0; }
    .brand h1 { font-family:'Playfair Display',serif; font-size:1.6rem; font-weight:900; letter-spacing:-0.02em; line-height:1.1; }
    .brand p  { font-size:0.78rem; font-weight:300; color:var(--mid); letter-spacing:0.12em; text-transform:uppercase; margin-top:2px; }
    main { max-width:560px; margin:0 auto; padding:2.5rem 1.5rem 4rem; }
    .closed-banner { background:#3a1a0a; color:#f5c5a0; border:2px solid var(--rust); border-radius:8px; padding:1.5rem; text-align:center; margin-bottom:2rem; }
    .closed-banner h2 { font-family:'Playfair Display',serif; font-size:1.3rem; margin-bottom:0.4rem; }
    .closed-banner p  { font-size:0.88rem; opacity:0.8; }
    .take-turn-card { background:var(--cream); border:2px solid var(--ink); border-radius:8px; padding:2rem; margin-bottom:2rem; text-align:center; position:relative; overflow:hidden; }
    .take-turn-card::after { content:''; position:absolute; bottom:-30px; right:-30px; width:120px; height:120px; border:3px solid var(--gold); border-radius:50%; opacity:0.25; }
    .take-turn-card h2 { font-family:'Playfair Display',serif; font-size:1.3rem; margin-bottom:1.2rem; }
    .btn-tomar { background:var(--rust); color:#fff; border:none; padding:1rem 2.5rem; font-family:'DM Sans',sans-serif; font-size:1rem; font-weight:500; border-radius:4px; cursor:pointer; letter-spacing:0.04em; transition:background 0.2s,transform 0.1s; }
    .btn-tomar:hover { background:#a33a08; transform:translateY(-1px); }
    .btn-tomar:disabled { background:var(--mid); cursor:not-allowed; transform:none; }
    .ticket-alert { background:var(--sage); color:#fff; border-radius:8px; padding:1.5rem 2rem; margin-bottom:2rem; display:flex; align-items:center; gap:1.5rem; animation:fadeIn 0.4s ease; }
    .ticket-num-big { font-family:'Playfair Display',serif; font-size:3.5rem; font-weight:900; line-height:1; flex-shrink:0; }
    .ticket-info h3 { font-size:0.75rem; text-transform:uppercase; letter-spacing:0.1em; opacity:0.8; }
    .ticket-info p  { font-size:1rem; margin-top:4px; }
    .queue-section h2 { font-family:'Playfair Display',serif; font-size:1.1rem; margin-bottom:1rem; display:flex; align-items:center; gap:8px; }
    .queue-section h2::after { content:''; flex:1; height:1px; background:var(--mid); opacity:0.4; }
    .queue-list { list-style:none; }
    .queue-list li { display:flex; align-items:center; padding:0.75rem 1rem; border-bottom:1px solid rgba(0,0,0,0.06); font-size:0.9rem; gap:12px; }
    .queue-list li:last-child { border-bottom:none; }
    .q-num { font-family:'Playfair Display',serif; font-weight:700; font-size:1.2rem; min-width:42px; }
    .q-badge { padding:2px 10px; border-radius:20px; font-size:0.72rem; font-weight:500; letter-spacing:0.05em; text-transform:uppercase; }
    .badge-waiting { background:#e8f4ec; color:var(--sage); }
    .badge-called  { background:#fff3e0; color:#b36200; }
    .empty-queue { text-align:center; padding:2rem; color:var(--mid); font-size:0.9rem; border:1px dashed var(--mid); border-radius:8px; opacity:0.7; }
    footer { text-align:center; padding:1rem; font-size:0.78rem; color:var(--mid); margin-top:2rem; }
    @keyframes fadeIn { from{opacity:0;transform:translateY(10px);} to{opacity:1;transform:none;} }
  </style>
</head>
<body>
<header>
  <div class="logo-mark">PE</div>
  <div class="brand"><h1>Papelería Espacios</h1><p>Sistema de turnos en línea</p></div>
</header>
<main>
  {% if not sesion_abierta %}
  <div class="closed-banner">
    <h2>&#9888; Jornada no iniciada</h2>
    <p>El sistema de turnos no está activo en este momento.</p>
  </div>
  {% endif %}

  {% if ticket %}
  <div class="ticket-alert">
    <div class="ticket-num-big">{{ ticket.numero }}</div>
    <div class="ticket-info">
      <h3>Tu número de turno</h3>
      <p>Posición en cola: <strong>{{ posicion }}</strong></p>
      <p style="font-size:0.82rem;opacity:0.85;margin-top:4px;">Refresca la página para actualizar tu posición.</p>
    </div>
  </div>
  {% endif %}

  <div class="take-turn-card">
    <h2>¿Listo para ser atendido?</h2>
    <form method="post" action="{{ url_for('tomar_turno') }}">
      <button class="btn-tomar" type="submit" {% if not sesion_abierta %}disabled{% endif %}>
        {% if sesion_abierta %}Tomar un turno{% else %}Sistema cerrado{% endif %}
      </button>
    </form>
  </div>

  {% if sesion_abierta %}
  <div class="queue-section">
    <h2>Cola actual</h2>
    {% if cola %}
    <ul class="queue-list">
      {% for t in cola %}
      <li>
        <span class="q-num">{{ t.numero }}</span>
        <span class="q-badge {% if t.estado == 'called' %}badge-called{% else %}badge-waiting{% endif %}">
          {{ 'Llamado' if t.estado == 'called' else 'Esperando' }}
        </span>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <div class="empty-queue">No hay turnos en espera por el momento.</div>
    {% endif %}
  </div>
  {% endif %}
</main>
<footer>Papelería Espacios &copy; {{ now.year }} &mdash; Av. Principal, Mérida, Yucatán</footer>
</body>
</html>
"""

# ══════════════════════════════════════════════════════════════
#  TEMPLATE EMPLEADO
# ══════════════════════════════════════════════════════════════

TEMPLATE_EMPLEADO = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Papelería Espacios — Empleados</title>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
  <style>
    :root { --ink:#1a1209; --paper:#fdf8ef; --cream:#f5ead6; --rust:#c0440a; --gold:#d4940a; --sage:#4a7c59; --mid:#8c7a60; }
    *, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
    body { font-family:'DM Sans',sans-serif; background:#1e1a11; color:var(--paper); min-height:100vh; }
    header { background:#12100a; padding:1.2rem 2rem; display:flex; align-items:center; justify-content:space-between; border-bottom:3px solid var(--rust); }
    .header-left { display:flex; align-items:center; gap:1.2rem; }
    .logo-mark { width:46px; height:46px; background:var(--rust); border-radius:4px; display:flex; align-items:center; justify-content:center; font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:900; }
    .brand h1 { font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:900; }
    .brand p  { font-size:0.72rem; color:var(--mid); letter-spacing:0.1em; text-transform:uppercase; margin-top:1px; }
    .panel-badge { background:rgba(192,68,10,0.25); color:var(--rust); border:1px solid rgba(192,68,10,0.4); padding:4px 14px; border-radius:20px; font-size:0.78rem; font-weight:500; letter-spacing:0.06em; }
    main { max-width:1000px; margin:0 auto; padding:2rem 1.5rem 4rem; }

    .jornada-bar { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:1rem; background:#28221a; border:1px solid rgba(255,255,255,0.07); border-radius:10px; padding:1rem 1.5rem; margin-bottom:1.5rem; }
    .jornada-info { display:flex; align-items:center; gap:10px; }
    .jornada-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
    .dot-open   { background:#7ec89a; animation:pulse 2s infinite; }
    .dot-closed { background:#e05555; }
    .jornada-label { font-size:0.88rem; }
    .jornada-label strong { font-size:1rem; }
    .jornada-actions { display:flex; gap:0.75rem; flex-wrap:wrap; }

    .stat-row { display:flex; gap:1rem; margin-bottom:1.5rem; flex-wrap:wrap; }
    .stat-box { flex:1; min-width:110px; background:#28221a; border:1px solid rgba(255,255,255,0.07); border-radius:8px; padding:1rem; text-align:center; }
    .stat-val { font-family:'Playfair Display',serif; font-size:2rem; font-weight:700; color:var(--gold); }
    .stat-lbl { font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--mid); margin-top:2px; }

    .grid { display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; margin-bottom:1.5rem; }
    @media(max-width:640px){ .grid{grid-template-columns:1fr;} }

    .card { background:#28221a; border:1px solid rgba(255,255,255,0.07); border-radius:10px; padding:1.5rem; }
    .card-title { font-size:0.7rem; font-weight:500; text-transform:uppercase; letter-spacing:0.12em; color:var(--mid); margin-bottom:1rem; }
    .current-number { font-family:'Playfair Display',serif; font-size:6rem; font-weight:900; line-height:1; color:var(--gold); text-align:center; padding:0.5rem 0 1rem; }
    .current-dash { color:rgba(255,255,255,0.2); }

    .btn-row { display:flex; gap:0.75rem; flex-wrap:wrap; }
    .btn { padding:0.7rem 1.3rem; border:none; border-radius:5px; font-family:'DM Sans',sans-serif; font-size:0.88rem; font-weight:500; cursor:pointer; transition:opacity 0.15s,transform 0.1s; text-decoration:none; display:inline-block; }
    .btn:hover  { opacity:0.88; transform:translateY(-1px); }
    .btn:active { transform:translateY(0); }
    .btn:disabled, .btn.disabled { opacity:0.4; cursor:not-allowed; transform:none; pointer-events:none; }
    .btn-green  { background:var(--sage); color:#fff; }
    .btn-outline{ background:transparent; color:var(--paper); border:1px solid rgba(255,255,255,0.25); }
    .btn-red    { background:var(--rust); color:#fff; }
    .btn-gold   { background:var(--gold); color:var(--ink); }
    .btn-dark   { background:#3a3020; color:var(--paper); border:1px solid rgba(255,255,255,0.15); }
    .btn-danger { background:#8a1a1a; color:#fff; }
    .btn-orange { background:#b05000; color:#fff; }

    .queue-list { list-style:none; max-height:260px; overflow-y:auto; }
    .queue-list::-webkit-scrollbar { width:4px; }
    .queue-list::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.1); border-radius:2px; }
    .queue-list li { display:flex; align-items:center; gap:10px; padding:0.6rem 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.88rem; }
    .queue-list li:last-child { border-bottom:none; }
    .q-num { font-family:'Playfair Display',serif; font-weight:700; font-size:1.1rem; min-width:36px; }
    .q-badge { padding:2px 10px; border-radius:20px; font-size:0.7rem; font-weight:500; letter-spacing:0.05em; text-transform:uppercase; }
    .badge-waiting { background:rgba(74,124,89,0.2); color:#7ec89a; }
    .badge-called  { background:rgba(212,148,10,0.2); color:var(--gold); }

    .report-section { margin-top:0; }
    .report-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:1rem; flex-wrap:wrap; gap:0.5rem; }
    .report-header h2 { font-family:'Playfair Display',serif; font-size:1.15rem; }
    .report-header span { font-size:0.75rem; color:var(--mid); }
    .report-table { width:100%; border-collapse:collapse; }
    .report-table th { text-align:left; padding:0.6rem 1rem; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.1em; color:var(--mid); border-bottom:1px solid rgba(255,255,255,0.07); }
    .report-table td { padding:0.7rem 1rem; font-size:0.88rem; border-bottom:1px solid rgba(255,255,255,0.04); }
    .report-table tr:last-child td { border-bottom:none; }
    .report-table tr:hover td { background:rgba(255,255,255,0.03); }
    .td-missed { color:#e07070; }
    .td-served { color:#7ec89a; }

    .client-link { margin-top:1rem; display:inline-block; color:var(--mid); font-size:0.82rem; text-decoration:none; }
    .client-link:hover { color:var(--paper); }

    /* Modal */
    .modal-bg { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:1000; align-items:center; justify-content:center; }
    .modal-bg.show { display:flex; }
    .modal-box { background:#28221a; border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:2rem; max-width:420px; width:90%; text-align:center; }
    .modal-box h3 { font-family:'Playfair Display',serif; font-size:1.3rem; margin-bottom:0.75rem; color:var(--gold); }
    .modal-box p  { font-size:0.9rem; color:var(--mid); margin-bottom:1.5rem; line-height:1.6; }
    .modal-actions { display:flex; gap:0.75rem; justify-content:center; }

    @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
  </style>
  <script>
    const jornadaActiva = {{ 'true' if sesion_abierta else 'false' }};

    async function llamarSiguiente() {
      const res = await fetch('/empleado/llamar_siguiente', {method:'POST'});
      const data = await res.json();
      if (data.error) { alert(data.error); return; }
      document.getElementById('actual').innerHTML = data.numero;
      cargarCola(); cargarReporte();
    }
    async function llamarEspecifico() {
      const numero = prompt("Introduce el número de turno a llamar:");
      if (!numero) return;
      const res = await fetch('/empleado/llamar_especifico', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({numero: parseInt(numero)})
      });
      const data = await res.json();
      if (data.error) { alert(data.error); return; }
      document.getElementById('actual').innerHTML = data.numero;
      cargarCola(); cargarReporte();
    }
    async function marcarPerdido() {
      if (!confirm('¿Marcar el turno actual como perdido (cliente no se presentó)?')) return;
      const res = await fetch('/empleado/marcar_perdido', {method:'POST'});
      const data = await res.json();
      if (data.error) { alert(data.error); return; }
      document.getElementById('actual').innerHTML = '<span class="current-dash">—</span>';
      cargarCola(); cargarReporte();
    }
    async function cargarCola() {
      const res = await fetch('/empleado/cola_json');
      const data = await res.json();
      const ul = document.getElementById('lista_cola');
      ul.innerHTML = '';
      if (data.length === 0) {
        ul.innerHTML = '<li style="color:var(--mid);padding:0.6rem 0;font-size:0.85rem;">Cola vacía</li>';
        return;
      }
      data.forEach(t => {
        const li = document.createElement('li');
        const cls = t.estado==='called' ? 'badge-called' : 'badge-waiting';
        const lbl = t.estado==='called' ? 'Llamado' : 'Esperando';
        li.innerHTML = `<span class="q-num">${t.numero}</span><span class="q-badge ${cls}">${lbl}</span>`;
        ul.appendChild(li);
      });
    }
    async function cargarReporte() {
      const res = await fetch('/empleado/reporte_hoy_json');
      const data = await res.json();
      document.getElementById('stat-total').innerText     = data.total;
      document.getElementById('stat-espera').innerText    = data.en_espera;
      document.getElementById('stat-atendidos').innerText = data.atendidos;
      document.getElementById('stat-perdidos').innerText  = data.perdidos;
      const tbody = document.getElementById('reporte-body');
      tbody.innerHTML = '';
      if (!data.todos || data.todos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--mid);padding:2rem;">Sin registros todavía.</td></tr>';
        return;
      }
      data.todos.forEach(t => {
        const tr = document.createElement('tr');
        const cls = t.estado==='served' ? 'td-served' : (t.estado==='missed' ? 'td-missed' : '');
        const etq = t.estado==='served' ? '&#10003; Atendido' : (t.estado==='missed' ? '&#10007; Perdido' : '&hellip;En curso');
        tr.innerHTML = `
          <td style="font-family:Playfair Display,serif;font-weight:700;">${t.numero}</td>
          <td>${t.llamado_en||'—'}</td>
          <td>${t.atendido_en||'—'}</td>
          <td class="${cls}">${etq}</td>`;
        tbody.appendChild(tr);
      });
    }
    function confirmarFin()    { document.getElementById('modal-fin').classList.add('show'); }
    function cancelarFin()     { document.getElementById('modal-fin').classList.remove('show'); }
    function confirmarInicio() { document.getElementById('modal-inicio').classList.add('show'); }
    function cancelarInicio()  { document.getElementById('modal-inicio').classList.remove('show'); }
    // ── CAMBIO: descarga PDF en lugar de TXT ──
    function descargarPdf()    { window.location.href='/empleado/descargar_reporte'; }
    window.onload = function() {
      cargarCola(); cargarReporte();
      setInterval(cargarCola,    5000);
      setInterval(cargarReporte, 10000);
      const el = document.getElementById('fecha-hoy');
      if (el) el.innerText = new Date().toLocaleDateString('es-MX',{weekday:'long',year:'numeric',month:'long',day:'numeric'});
    };
  </script>
</head>
<body>

<!-- Modal: Terminar jornada -->
<div class="modal-bg" id="modal-fin">
  <div class="modal-box">
    <h3>&#9888; Terminar jornada</h3>
    <p>Se cerrará la jornada actual. Los turnos en espera quedarán como <strong>perdidos</strong>.<br>Puedes descargar el reporte completo en PDF antes o después de cerrar.</p>
    <div class="modal-actions">
      <button class="btn btn-dark" onclick="cancelarFin()">Cancelar</button>
      <button class="btn btn-gold" onclick="descargarPdf(); cancelarFin();">&#11015; Descargar PDF</button>
      <a class="btn btn-danger" href="/empleado/terminar_jornada">&#9632; Terminar</a>
    </div>
  </div>
</div>

<!-- Modal: Iniciar jornada -->
<div class="modal-bg" id="modal-inicio">
  <div class="modal-box">
    <h3>Iniciar nueva jornada</h3>
    <p>El contador de turnos se reiniciará desde <strong>1</strong> y se abrirá una nueva sesión de atención.</p>
    <div class="modal-actions">
      <button class="btn btn-dark" onclick="cancelarInicio()">Cancelar</button>
      <a class="btn btn-green" href="/empleado/iniciar_jornada">&#9654; Iniciar</a>
    </div>
  </div>
</div>

<header>
  <div class="header-left">
    <div class="logo-mark">PE</div>
    <div class="brand"><h1>Papelería Espacios</h1><p>Panel de empleados</p></div>
  </div>
  <span class="panel-badge">Staff</span>
</header>

<main>
  <!-- Barra de jornada -->
  <div class="jornada-bar">
    <div class="jornada-info">
      <div class="jornada-dot {% if sesion_abierta %}dot-open{% else %}dot-closed{% endif %}"></div>
      <div class="jornada-label">
        {% if sesion_abierta %}
          <strong>Jornada activa</strong> &mdash; iniciada a las {{ hora_inicio }}
        {% else %}
          <strong>Jornada cerrada</strong> &mdash; sin sesión activa
        {% endif %}
      </div>
    </div>
    <div class="jornada-actions">
      {% if sesion_abierta %}
        <button class="btn btn-gold"   onclick="descargarPdf()">&#11015; Descargar PDF</button>
        <button class="btn btn-danger" onclick="confirmarFin()">&#9632; Terminar jornada</button>
      {% else %}
        <button class="btn btn-gold"   onclick="descargarPdf()">&#11015; Último reporte PDF</button>
        <button class="btn btn-green"  onclick="confirmarInicio()">&#9654; Iniciar jornada</button>
      {% endif %}
    </div>
  </div>

  <!-- Stats -->
  <div class="stat-row">
    <div class="stat-box"><div class="stat-val" id="stat-total">—</div><div class="stat-lbl">Turnos totales</div></div>
    <div class="stat-box"><div class="stat-val" id="stat-espera">—</div><div class="stat-lbl">En espera</div></div>
    <div class="stat-box"><div class="stat-val" id="stat-atendidos">—</div><div class="stat-lbl">Atendidos</div></div>
    <div class="stat-box"><div class="stat-val" id="stat-perdidos">—</div><div class="stat-lbl">Perdidos</div></div>
  </div>

  <div class="grid">
    <!-- Turno actual -->
    <div class="card">
      <div class="card-title">Turno en pantalla</div>
      <div class="current-number" id="actual">
        {% if actual_numero %}{{ actual_numero }}{% else %}<span class="current-dash">—</span>{% endif %}
      </div>
      <div class="btn-row">
        <button class="btn btn-green   {% if not sesion_abierta %}disabled{% endif %}" onclick="llamarSiguiente()">&#9654; Siguiente</button>
        <button class="btn btn-outline {% if not sesion_abierta %}disabled{% endif %}" onclick="llamarEspecifico()"># Específico</button>
        {% if sesion_abierta %}
          <a class="btn btn-red" href="/empleado/servir_actual">&#10003; Atendido</a>
        {% else %}
          <span class="btn btn-red disabled">&#10003; Atendido</span>
        {% endif %}
        <button class="btn btn-orange {% if not sesion_abierta %}disabled{% endif %}" onclick="marcarPerdido()">&#10007; Perdido</button>
      </div>
    </div>

    <!-- Cola en vivo -->
    <div class="card">
      <div class="card-title">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--sage);margin-right:6px;animation:pulse 2s infinite;"></span>
        Cola en vivo
      </div>
      <ul class="queue-list" id="lista_cola">
        <li style="color:var(--mid);padding:0.6rem 0;">Cargando&hellip;</li>
      </ul>
    </div>
  </div>

  <!-- Tabla de registro -->
  <div class="card report-section">
    <div class="report-header">
      <h2>Registro de turnos &mdash; sesión actual</h2>
      <span id="fecha-hoy"></span>
    </div>
    <table class="report-table">
      <thead>
        <tr><th>Turno</th><th>Llamado a las</th><th>Fin a las</th><th>Estado</th></tr>
      </thead>
      <tbody id="reporte-body">
        <tr><td colspan="4" style="text-align:center;padding:2rem;color:var(--mid);">Cargando&hellip;</td></tr>
      </tbody>
    </table>
  </div>

  <a class="client-link" href="/">&#8592; Ver pantalla de clientes</a>
</main>
</body>
</html>
"""

# ══════════════════════════════════════════════════════════════
#  RUTAS — CLIENTE
# ══════════════════════════════════════════════════════════════

@app.route('/', methods=['GET'])
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
    return render_template_string(TEMPLATE_CLIENTE,
        ticket=ticket, posicion=posicion, cola=cola,
        sesion_abierta=bool(s), now=datetime.utcnow())


@app.route('/tomar_turno', methods=['POST'])
def tomar_turno():
    s = sesion_activa()
    if not s:
        return redirect(url_for('cliente_index'))
    # Registro del turno con sesion_id explícito
    nuevo = Ticket(
        sesion_id=s.id,
        numero=proximo_numero(s),
        estado='waiting'
    )
    db.session.add(nuevo)
    db.session.commit()
    return redirect(url_for('cliente_index', ticket_id=nuevo.id))


# ══════════════════════════════════════════════════════════════
#  RUTAS — EMPLEADO
# ══════════════════════════════════════════════════════════════

@app.route('/empleado')
def empleado_index():
    s = sesion_activa()
    ultimo_llamado = hora_inicio = None
    if s:
        ultimo_llamado = Ticket.query.filter(
            Ticket.sesion_id == s.id,
            Ticket.estado == 'called'
        ).order_by(Ticket.llamado_en.desc()).first()
        hora_inicio = s.iniciada_en.strftime('%H:%M')
    return render_template_string(TEMPLATE_EMPLEADO,
        actual_numero=ultimo_llamado.numero if ultimo_llamado else None,
        sesion_abierta=bool(s), hora_inicio=hora_inicio)


# ── Gestión de jornada ─────────────────────────────────────────

@app.route('/empleado/iniciar_jornada')
def iniciar_jornada():
    # Cierra cualquier jornada previa activa
    Sesion.query.filter_by(activa=True).update(
        {'activa': False, 'cerrada_en': datetime.utcnow()}
    )
    # Crea la nueva sesión (los tickets se vinculan con sesion_id)
    nueva = Sesion()
    db.session.add(nueva)
    db.session.commit()
    return redirect(url_for('empleado_index'))


@app.route('/empleado/terminar_jornada')
def terminar_jornada():
    s = sesion_activa()
    if s:
        # Marca como perdidos todos los turnos pendientes de esta sesión
        Ticket.query.filter(
            Ticket.sesion_id == s.id,
            Ticket.estado.in_(['waiting', 'called'])
        ).update({'estado': 'missed', 'atendido_en': datetime.utcnow()},
                 synchronize_session=False)
        s.activa = False
        s.cerrada_en = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('empleado_index'))


# ── Cola JSON ──────────────────────────────────────────────────

@app.route('/empleado/cola_json')
def empleado_cola_json():
    s = sesion_activa()
    if not s:
        return jsonify([])
    cola = Ticket.query.filter(
        Ticket.sesion_id == s.id,
        Ticket.estado.in_(['waiting', 'called'])
    ).order_by(Ticket.numero.asc()).limit(50).all()
    return jsonify([{'id': t.id, 'numero': t.numero, 'estado': t.estado} for t in cola])


# ── Acciones de turno ──────────────────────────────────────────

@app.route('/empleado/llamar_siguiente', methods=['POST'])
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


@app.route('/empleado/llamar_especifico', methods=['POST'])
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


@app.route('/empleado/servir_actual')
def empleado_servir_actual():
    s = sesion_activa()
    if not s:
        return redirect(url_for('empleado_index'))
    t = Ticket.query.filter(
        Ticket.sesion_id == s.id,
        Ticket.estado == 'called'
    ).order_by(Ticket.llamado_en.desc()).first()
    if t:
        t.estado = 'served'
        t.atendido_en = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('empleado_index'))


@app.route('/empleado/marcar_perdido', methods=['POST'])
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


# ── Reporte JSON ───────────────────────────────────────────────

@app.route('/empleado/reporte_hoy_json')
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


# ══════════════════════════════════════════════════════════════
#  DESCARGA PDF — reemplaza la descarga TXT original
# ══════════════════════════════════════════════════════════════

def _generar_pdf(s) -> bytes:
    """Construye el PDF del reporte de jornada y devuelve los bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title='Reporte de jornada — Papelería Espacios'
    )

    # ── Estilos ──────────────────────────────────────────────
    styles = getSampleStyleSheet()
    s_title = ParagraphStyle(
        'PE_Title', parent=styles['Title'],
        fontSize=22, textColor=colors.HexColor('#1a1209'),
        spaceAfter=4
    )
    s_sub = ParagraphStyle(
        'PE_Sub', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor('#8c7a60'),
        spaceAfter=2
    )
    s_section = ParagraphStyle(
        'PE_Section', parent=styles['Heading2'],
        fontSize=10, textColor=colors.HexColor('#c0440a'),
        spaceBefore=14, spaceAfter=6,
        borderPad=0
    )
    s_normal = ParagraphStyle(
        'PE_Normal', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor('#1a1209'),
        leading=14
    )
    s_footer = ParagraphStyle(
        'PE_Footer', parent=styles['Normal'],
        fontSize=8, textColor=colors.HexColor('#8c7a60'),
        alignment=TA_CENTER, spaceBefore=20
    )

    # ── Datos ────────────────────────────────────────────────
    tickets   = tickets_de_sesion(s)
    atendidos = [t for t in tickets if t.estado == 'served']
    perdidos  = [t for t in tickets if t.estado == 'missed']
    en_espera = [t for t in tickets if t.estado in ('waiting', 'called')]

    def fmt(dt): return dt.strftime('%H:%M:%S') if dt else '—'
    def fmtdt(dt): return dt.strftime('%d/%m/%Y  %H:%M') if dt else '—'

    # ── Construcción del contenido ───────────────────────────
    story = []

    # Encabezado
    story.append(Paragraph('Papelería Espacios', s_title))
    story.append(Paragraph('Reporte de jornada de trabajo', s_sub))
    story.append(HRFlowable(width='100%', thickness=2,
                             color=colors.HexColor('#c0440a'), spaceAfter=10))

    # Resumen de la jornada
    resumen_data = [
        ['Fecha del reporte',  datetime.utcnow().strftime('%d/%m/%Y')],
        ['Inicio de jornada',  fmtdt(s.iniciada_en)],
        ['Fin de jornada',     fmtdt(s.cerrada_en) if s.cerrada_en else 'Jornada aún activa'],
        ['Sesión ID',          str(s.id)],
    ]
    resumen_table = Table(resumen_data, colWidths=[5*cm, 9*cm])
    resumen_table.setStyle(TableStyle([
        ('FONTNAME',    (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE',    (0, 0), (-1, -1), 9),
        ('FONTNAME',    (0, 0), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR',   (0, 0), (0, -1), colors.HexColor('#1a1209')),
        ('TEXTCOLOR',   (1, 0), (1, -1), colors.HexColor('#3a3020')),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1),
         [colors.HexColor('#fdf8ef'), colors.HexColor('#f5ead6')]),
        ('GRID',        (0, 0), (-1, -1), 0.5, colors.HexColor('#d4c5a9')),
        ('PADDING',     (0, 0), (-1, -1), 6),
    ]))
    story.append(resumen_table)
    story.append(Spacer(1, 14))

    # Totales
    story.append(Paragraph('Resumen de turnos', s_section))
    totales_data = [
        ['Total de turnos', 'Atendidos', 'Perdidos', 'En espera'],
        [str(len(tickets)), str(len(atendidos)), str(len(perdidos)), str(len(en_espera))],
    ]
    totales_table = Table(totales_data, colWidths=[4*cm]*4)
    totales_table.setStyle(TableStyle([
        ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, -1), 9),
        ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
        ('BACKGROUND',  (0, 0), (-1, 0), colors.HexColor('#1a1209')),
        ('TEXTCOLOR',   (0, 0), (-1, 0), colors.HexColor('#fdf8ef')),
        ('FONTNAME',    (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE',    (0, 1), (-1, 1), 16),
        ('TEXTCOLOR',   (0, 1), (0, 1), colors.HexColor('#1a1209')),
        ('TEXTCOLOR',   (1, 1), (1, 1), colors.HexColor('#4a7c59')),
        ('TEXTCOLOR',   (2, 1), (2, 1), colors.HexColor('#c0440a')),
        ('TEXTCOLOR',   (3, 1), (3, 1), colors.HexColor('#d4940a')),
        ('GRID',        (0, 0), (-1, -1), 0.5, colors.HexColor('#d4c5a9')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#fdf8ef')]),
        ('PADDING',     (0, 0), (-1, -1), 8),
    ]))
    story.append(totales_table)
    story.append(Spacer(1, 14))

    # ── Tabla de turnos atendidos ────────────────────────────
    story.append(Paragraph('Detalle — Turnos atendidos', s_section))
    if atendidos:
        header = [['#', 'Tomado a las', 'Llamado a las', 'Atendido a las']]
        rows = [
            [str(t.numero), fmt(t.creado), fmt(t.llamado_en), fmt(t.atendido_en)]
            for t in atendidos
        ]
        det_table = Table(header + rows, colWidths=[2*cm, 4*cm, 4*cm, 4*cm])
        det_table.setStyle(TableStyle([
            ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',    (0, 0), (-1, -1), 9),
            ('BACKGROUND',  (0, 0), (-1, 0), colors.HexColor('#4a7c59')),
            ('TEXTCOLOR',   (0, 0), (-1, 0), colors.white),
            ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.HexColor('#eaf4ee'), colors.HexColor('#fdf8ef')]),
            ('GRID',        (0, 0), (-1, -1), 0.5, colors.HexColor('#c5dbc9')),
            ('PADDING',     (0, 0), (-1, -1), 6),
        ]))
        story.append(det_table)
    else:
        story.append(Paragraph('(ningún turno atendido en esta jornada)', s_normal))

    story.append(Spacer(1, 14))

    # ── Tabla de turnos perdidos ─────────────────────────────
    story.append(Paragraph('Detalle — Turnos perdidos', s_section))
    if perdidos:
        header = [['#', 'Tomado a las', 'Llamado a las', 'Registrado a las']]
        rows = [
            [str(t.numero), fmt(t.creado), fmt(t.llamado_en), fmt(t.atendido_en)]
            for t in perdidos
        ]
        per_table = Table(header + rows, colWidths=[2*cm, 4*cm, 4*cm, 4*cm])
        per_table.setStyle(TableStyle([
            ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',    (0, 0), (-1, -1), 9),
            ('BACKGROUND',  (0, 0), (-1, 0), colors.HexColor('#c0440a')),
            ('TEXTCOLOR',   (0, 0), (-1, 0), colors.white),
            ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.HexColor('#fdf0ea'), colors.HexColor('#fdf8ef')]),
            ('GRID',        (0, 0), (-1, -1), 0.5, colors.HexColor('#e8c5b0')),
            ('PADDING',     (0, 0), (-1, -1), 6),
        ]))
        story.append(per_table)
    else:
        story.append(Paragraph('(ningún turno perdido en esta jornada)', s_normal))

    # ── En espera (si la jornada estaba activa al momento del reporte) ──
    if en_espera:
        story.append(Spacer(1, 14))
        story.append(Paragraph('Turnos en espera al momento del reporte', s_section))
        header = [['#', 'Tomado a las', 'Estado']]
        rows = [
            [str(t.numero), fmt(t.creado),
             'Llamado' if t.estado == 'called' else 'Esperando']
            for t in en_espera
        ]
        esp_table = Table(header + rows, colWidths=[2*cm, 5*cm, 7*cm])
        esp_table.setStyle(TableStyle([
            ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',    (0, 0), (-1, -1), 9),
            ('BACKGROUND',  (0, 0), (-1, 0), colors.HexColor('#d4940a')),
            ('TEXTCOLOR',   (0, 0), (-1, 0), colors.HexColor('#1a1209')),
            ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.HexColor('#fdf8ef'), colors.HexColor('#fdf3dc')]),
            ('GRID',        (0, 0), (-1, -1), 0.5, colors.HexColor('#e8d5a0')),
            ('PADDING',     (0, 0), (-1, -1), 6),
        ]))
        story.append(esp_table)

    # Pie de página
    story.append(HRFlowable(width='100%', thickness=1,
                             color=colors.HexColor('#d4c5a9'), spaceBefore=20))
    story.append(Paragraph(
        f'Generado por el sistema de Papelería Espacios &bull; '
        f'{datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")} UTC',
        s_footer
    ))

    doc.build(story)
    return buffer.getvalue()


@app.route('/empleado/descargar_reporte')
def descargar_reporte():
    """Descarga el reporte de jornada como PDF (antes era .txt)."""
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


# ── API estado ─────────────────────────────────────────────────

@app.route('/api/estado')
def api_estado():
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


# ── Arranque ───────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
