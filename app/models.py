from datetime import datetime
from app.extensions import db

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
