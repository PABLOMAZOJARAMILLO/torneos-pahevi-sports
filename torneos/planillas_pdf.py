from io import BytesIO
from datetime import date

from PIL import Image, ImageDraw, ImageFont
from django.utils.text import slugify

PAGE_W = 2148
PAGE_H = 3038
PDF_DPI = 200
MARGIN = 70
BLACK = "#111111"
GRAY = "#666666"
LIGHT = "#F3F4F6"
BORDER = "#1F2937"


def _font(size, bold=False):
    candidates = []
    if bold:
        candidates.extend([
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
        ])
    candidates.extend([
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "arial.ttf",
    ])
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


FONT_TITLE = _font(34, True)
FONT_HEAD = _font(24, True)
FONT_NORMAL = _font(22)
FONT_SMALL = _font(18)
FONT_SMALL_BOLD = _font(18, True)
FONT_TINY = _font(15)


def _clean(value, default=""):
    if value is None:
        return default
    return str(value).strip() or default


def _fecha(value):
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def _hora(value):
    if not value:
        return ""
    return value.strftime("%I:%M %p").lower().replace("am", "a. m.").replace("pm", "p. m.")


def _edad(fecha_nacimiento, referencia=None):
    if not fecha_nacimiento:
        return ""
    referencia = referencia or date.today()
    return str(referencia.year - fecha_nacimiento.year - ((referencia.month, referencia.day) < (fecha_nacimiento.month, fecha_nacimiento.day)))


def _fase(partido):
    if partido.fase == "GRUPOS":
        return _clean(partido.numero_fecha, "FECHA")
    return partido.get_fase_display().upper()


def nombre_archivo_planilla(partido, extension="pdf"):
    base = f"{partido.categoria.nombre} - {partido.equipo_local.nombre} VS {partido.equipo_visitante.nombre} - {_fase(partido)} - {_fecha(partido.fecha).replace('/', '-')}"
    return f"{slugify(base).upper() or 'PLANILLA'}.{extension}"


def _fit(draw, text, font, max_width):
    text = _clean(text)
    if not text:
        return ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text + ellipsis if text else ""


def _center(draw, box, text, font, fill=BLACK):
    x1, y1, x2, y2 = box
    text = _clean(text)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2 - 2), text, font=font, fill=fill)


def _label_value(draw, x, y, label, value, label_w=210, value_w=420):
    draw.rectangle([x, y, x + label_w, y + 42], outline=BORDER, width=2, fill=LIGHT)
    draw.rectangle([x + label_w, y, x + label_w + value_w, y + 42], outline=BORDER, width=2)
    draw.text((x + 10, y + 8), label, font=FONT_SMALL_BOLD, fill=BLACK)
    draw.text((x + label_w + 10, y + 8), _fit(draw, value, FONT_SMALL_BOLD, value_w - 20), font=FONT_SMALL_BOLD, fill=BLACK)


def _draw_player_table(draw, x, y, w, title, jugadores, referencia):
    draw.rectangle([x, y, x + w, y + 44], outline=BORDER, width=2, fill=LIGHT)
    _center(draw, (x, y, x + w, y + 44), title, FONT_SMALL_BOLD)

    headers = ["No", "NOMBRE Y APELLIDOS", "#", "EDAD", "INIC", "A", "R"]
    widths = [58, w - 430, 62, 72, 70, 52, 52]
    row_h = 45
    yy = y + 44
    xx = x
    for header, cw in zip(headers, widths):
        draw.rectangle([xx, yy, xx + cw, yy + row_h], outline=BORDER, width=2, fill=LIGHT)
        _center(draw, (xx, yy, xx + cw, yy + row_h), header, FONT_TINY if header != "NOMBRE Y APELLIDOS" else FONT_SMALL_BOLD)
        xx += cw

    jugadores = list(jugadores)[:30]
    for idx in range(30):
        jugador = jugadores[idx] if idx < len(jugadores) else None
        yy = y + 44 + row_h * (idx + 1)
        values = [str(idx + 1), "", "", "", "", "", ""]
        if jugador:
            values = [
                str(idx + 1),
                _clean(jugador.nombres).title(),
                _clean(jugador.dorsal),
                _edad(jugador.fecha_nacimiento, referencia),
                "",
                "",
                "",
            ]
        xx = x
        for pos, cw in enumerate(widths):
            draw.rectangle([xx, yy, xx + cw, yy + row_h], outline=BORDER, width=1)
            if pos == 1:
                draw.text((xx + 8, yy + 10), _fit(draw, values[pos], FONT_SMALL, cw - 16), font=FONT_SMALL, fill=BLACK)
            else:
                _center(draw, (xx, yy, xx + cw, yy + row_h), values[pos], FONT_SMALL)
            xx += cw

    return y + 44 + row_h * 31


def _draw_goals(draw, x, y, w, title):
    draw.rectangle([x, y, x + w, y + 40], outline=BORDER, width=2, fill=LIGHT)
    _center(draw, (x, y, x + w, y + 40), title, FONT_SMALL_BOLD)
    cell_w = w / 6
    cell_h = 54
    for row in range(2):
        for col in range(6):
            n = row * 6 + col + 1
            x1 = x + col * cell_w
            y1 = y + 40 + row * cell_h
            draw.rectangle([x1, y1, x1 + cell_w, y1 + cell_h], outline=BORDER, width=1)
            draw.text((x1 + 8, y1 + 6), f"GOL {n}", font=FONT_TINY, fill=GRAY)
            draw.text((x1 + cell_w - 34, y1 + 26), "#", font=FONT_SMALL_BOLD, fill=BLACK)


def _draw_changes(draw, x, y, w):
    draw.rectangle([x, y, x + w, y + 40], outline=BORDER, width=2, fill=LIGHT)
    _center(draw, (x, y, x + w, y + 40), "CONTROL DE CAMBIOS", FONT_SMALL_BOLD)
    headers = ["E", "S", "MIN", "E", "S", "MIN", "E", "S", "MIN"]
    cw = w / len(headers)
    for i, header in enumerate(headers):
        x1 = x + i * cw
        draw.rectangle([x1, y + 40, x1 + cw, y + 88], outline=BORDER, width=1)
        _center(draw, (x1, y + 40, x1 + cw, y + 88), header, FONT_TINY)


def generar_planilla_juego_pdf(partido):
    img = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(img)

    title = "PLANILLA DE JUEGO TORNEO VERANERO: SENIOR MASTER, PLUS 50 E INTERBARRIOS"
    _center(draw, (MARGIN, 42, PAGE_W - MARGIN, 100), title, FONT_TITLE)

    top_y = 126
    _label_value(draw, MARGIN, top_y, "FECHAS:", _fase(partido), 170, 520)
    _label_value(draw, PAGE_W - MARGIN - 620, top_y, "FECHA", _fecha(partido.fecha), 180, 440)
    _label_value(draw, MARGIN, top_y + 48, "CATEGORIA", partido.categoria.nombre.upper(), 220, 470)
    _label_value(draw, PAGE_W - MARGIN - 620, top_y + 48, "HORA", _hora(partido.hora), 180, 440)
    _label_value(draw, MARGIN, top_y + 96, "CANCHA", _clean(partido.cancha, ""), 220, 470)
    _label_value(draw, PAGE_W - MARGIN - 620, top_y + 96, "ARBITRO", "", 180, 440)

    team_y = top_y + 154
    half = (PAGE_W - MARGIN * 2 - 28) / 2
    _label_value(draw, MARGIN, team_y, "Equipo A:", partido.equipo_local.nombre.upper(), 180, int(half - 180))
    _label_value(draw, int(MARGIN + half + 28), team_y, "Equipo B:", partido.equipo_visitante.nombre.upper(), 180, int(half - 180))
    _label_value(draw, PAGE_W // 2 - 170, team_y + 54, "MARCADOR", "", 160, 180)

    referencia = partido.fecha or date.today()
    jugadores_local = partido.equipo_local.jugadores.filter(estado="ACTIVO").order_by("dorsal", "nombres")
    jugadores_visitante = partido.equipo_visitante.jugadores.filter(estado="ACTIVO").order_by("dorsal", "nombres")

    table_y = team_y + 110
    left_x = MARGIN
    right_x = int(MARGIN + half + 28)
    table_w = int(half)
    bottom_tables = _draw_player_table(draw, left_x, table_y, table_w, "LISTADO DE JUGADORES - EQUIPO A", jugadores_local, referencia)
    _draw_player_table(draw, right_x, table_y, table_w, "LISTADO DE JUGADORES - EQUIPO B", jugadores_visitante, referencia)

    section_y = bottom_tables + 32
    _draw_goals(draw, left_x, section_y, table_w, "GOLES")
    _draw_goals(draw, right_x, section_y, table_w, "GOLES")
    _draw_changes(draw, left_x, section_y + 172, table_w)
    _draw_changes(draw, right_x, section_y + 172, table_w)

    sign_y = section_y + 292
    draw.line([left_x, sign_y, left_x + table_w, sign_y], fill=BORDER, width=2)
    draw.text((left_x + 8, sign_y + 10), "Firma Delegado Equipo A:", font=FONT_SMALL_BOLD, fill=BLACK)
    draw.line([right_x, sign_y, right_x + table_w, sign_y], fill=BORDER, width=2)
    draw.text((right_x + 8, sign_y + 10), "Firma Delegado Equipo B:", font=FONT_SMALL_BOLD, fill=BLACK)

    obs_y = sign_y + 72
    draw.rectangle([MARGIN, obs_y, PAGE_W - MARGIN, obs_y + 96], outline=BORDER, width=2)
    draw.text((MARGIN + 12, obs_y + 10), "OBSERVACIONES:", font=FONT_SMALL_BOLD, fill=BLACK)

    output = BytesIO()
    img.save(output, format="PDF", resolution=PDF_DPI)
    return output.getvalue()
