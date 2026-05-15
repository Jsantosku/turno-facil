import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from app.utils import tickets_de_sesion

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
