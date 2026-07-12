from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from django.utils.text import slugify
import requests

PAGE_W = 2148
PAGE_H = 3038
PDF_DPI = 200
MARGIN_X = 70
MARGIN_Y = 80

BLACK = "#000000"
BORDER = "#000000"
LIGHT = "#F2F2F2"
WHITE = "#FFFFFF"

COL_WIDTHS = [
    4.5, 7.0, 15.0, 15.0, 15.0, 15.0, 7.0, 5.5, 5.5,
    5.5, 5.5, 5.5, 5.5, 4.5, 4.5, 7.0, 15.0, 15.0,
    15.0, 15.0, 7.0, 5.5, 5.5, 5.5, 5.5, 5.5, 5.5,
]
ROW_HEIGHTS = [
    15, 15, 15, 13.5, 19.5, 15.75, 15.75, 15.75, 16.5, 20.1,
    30.0, *([15.75] * 30), 16.5, 15.0, *([20.25] * 6),
    15.75, 15.0, 20.25, 15.0, 20.25, *([13.5] * 4), 15.0,
]


def _font(size, bold=False):
    candidates = []
    if bold:
        candidates.extend([
            r"C:\Windows\Fonts\timesbd.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman_Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ])
    candidates.extend([
        r"C:\Windows\Fonts\times.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
    ])
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


FONT_TITLE = _font(36, True)
FONT_HEAD = _font(31, True)
FONT_NORMAL = _font(31)
FONT_SMALL = _font(31)
FONT_SMALL_BOLD = _font(31, True)
FONT_TINY = _font(31)
FONT_TINY_BOLD = _font(31, True)

STATIC_IMG_DIR = Path(__file__).resolve().parent / "static" / "torneos" / "img"
HEADER_IMAGE_SLOTS = [
    (1, 1, 7, 4, "logo_izquierdo", None),
    (8, 1, 17, 4, "imagen_central", STATIC_IMG_DIR / "planilla_header_center.png"),
    (18, 1, 27, 4, "logo_derecho", None),
]


def _clean(value, default=""):
    if value is None:
        return default
    return str(value).strip() or default


def _fecha(value):
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def _fecha_con_dia(value):
    if not value:
        return ""
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    return f"{dias[value.weekday()]} {value.day}/{value.month:02d}/{value.year}"


def _hora(value):
    if not value:
        return ""
    return value.strftime("%I:%M %p").lower().replace("am", "a. m.").replace("pm", "p. m.")


def _edad(fecha_nacimiento, referencia=None):
    if not fecha_nacimiento:
        return ""
    referencia = referencia or date.today()
    return str(
        referencia.year
        - fecha_nacimiento.year
        - ((referencia.month, referencia.day) < (fecha_nacimiento.month, fecha_nacimiento.day))
    )


def _dorsal(value):
    if value in (None, "", 0, "0"):
        return ""
    return _clean(value)


def _fase(partido):
    if partido.fase == "GRUPOS":
        return _clean(partido.numero_fecha, "FECHA")
    return partido.get_fase_display().upper()


def _titulo_planilla(partido):
    torneo = getattr(getattr(partido, "categoria", None), "torneo", None)
    nombre_torneo = _clean(getattr(torneo, "nombre", ""), "TORNEO").upper()
    descripcion = _clean(getattr(torneo, "descripcion", "")).upper()
    if descripcion:
        return f"PLANILLA DE JUEGO {nombre_torneo} {descripcion}"
    return f"PLANILLA DE JUEGO {nombre_torneo}"


def nombre_archivo_planilla(partido, extension="pdf"):
    base = (
        f"{partido.categoria.nombre} - {partido.equipo_local.nombre} VS "
        f"{partido.equipo_visitante.nombre} - {_fase(partido)} - "
        f"{_fecha(partido.fecha).replace('/', '-')}"
    )
    return f"{slugify(base).upper() or 'PLANILLA'}.{extension}"


def _positions(lengths, start, end):
    total = sum(lengths)
    scale = (end - start) / total
    positions = [start]
    current = start
    for item in lengths:
        current += item * scale
        positions.append(current)
    return positions


X = _positions(COL_WIDTHS, MARGIN_X, PAGE_W - MARGIN_X)
Y = _positions(ROW_HEIGHTS, MARGIN_Y, PAGE_H - MARGIN_Y)


def _box(col1, row1, col2, row2):
    return [X[col1 - 1], Y[row1 - 1], X[col2], Y[row2]]


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


def _text(draw, box, text, font=FONT_NORMAL, align="center", valign="middle", bold=False):
    x1, y1, x2, y2 = box
    text = _clean(text)
    font = font or (FONT_SMALL_BOLD if bold else FONT_SMALL)
    text = _fit(draw, text, font, max(8, x2 - x1 - 8))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    if align == "left":
        x = x1 + 6
    elif align == "right":
        x = x2 - tw - 6
    else:
        x = x1 + (x2 - x1 - tw) / 2
    if valign == "top":
        y = y1 + 4
    elif valign == "bottom":
        y = y2 - th - 4
    else:
        y = y1 + (y2 - y1 - th) / 2 - 1
    draw.text((x, y), text, font=font, fill=BLACK)


def _vertical_text(base, box, text, font=FONT_TINY_BOLD):
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    text = _clean(text)
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    label = Image.new("RGBA", (tw + 8, th + 8), (255, 255, 255, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((4 - bbox[0], 4 - bbox[1]), text, font=font, fill=BLACK)
    label = label.rotate(90, expand=True)
    x = x1 + (x2 - x1 - label.width) // 2
    y = y1 + (y2 - y1 - label.height) // 2
    base.paste(label, (x, y), label)


def _cell(draw, col1, row1, col2=None, row2=None, text="", fill=WHITE, font=FONT_SMALL, align="center", valign="middle", width=1):
    col2 = col2 or col1
    row2 = row2 or row1
    box = _box(col1, row1, col2, row2)
    draw.rectangle(box, outline=BORDER, width=width, fill=fill)
    if text not in (None, ""):
        _text(draw, box, text, font=font, align=align, valign=valign)


def _image_from_source(source):
    if not source:
        return None

    if isinstance(source, Path):
        if not source.exists():
            return None
        return Image.open(source)

    try:
        if hasattr(source, "open"):
            source.open("rb")
            return Image.open(source)
    except Exception:
        pass

    url = getattr(source, "url", None) or str(source)
    if url.startswith(("http://", "https://")):
        try:
            response = requests.get(url, timeout=8)
            response.raise_for_status()
            return Image.open(BytesIO(response.content))
        except Exception:
            return None

    return None


def _draw_image_fit(base, source, box, padding=8):
    image = _image_from_source(source)
    if image is None:
        return
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    with image:
        image = image.convert("RGBA")
        image.thumbnail((max(1, x2 - x1 - padding), max(1, y2 - y1 - padding)), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (x2 - x1, y2 - y1), (255, 255, 255, 255))
        canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2), image)
        base.paste(canvas.convert("RGB"), (x1, y1))


def _team_shield_source(equipo):
    escudo = getattr(equipo, "escudo", None)
    if escudo:
        return escudo
    return None


def _draw_team_shield(base, draw, equipo, col1, row1, col2, row2):
    _cell(draw, col1, row1, col2, row2, fill=WHITE, width=2)
    _draw_image_fit(base, _team_shield_source(equipo), _box(col1, row1, col2, row2), padding=4)


def _draw_team_watermark(base, equipo, box, opacity=110):
    image = _image_from_source(_team_shield_source(equipo))
    if image is None:
        return

    x1, y1, x2, y2 = [int(round(value)) for value in box]
    with image:
        image = image.convert("RGBA")
        target_w = max(1, int((x2 - x1) * 0.92))
        target_h = max(1, int((y2 - y1) * 0.92))
        image.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        alpha = image.getchannel("A").point(lambda value: min(value, opacity))
        image.putalpha(alpha)
        layer = Image.new("RGBA", base.size, (255, 255, 255, 0))
        px = x1 + ((x2 - x1) - image.width) // 2
        py = y1 + ((y2 - y1) - image.height) // 2
        layer.paste(image, (px, py), image)
        composed = Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")
        base.paste(composed)


def _header_image_sources(partido):
    torneo = getattr(getattr(partido, "categoria", None), "torneo", None)
    sources = []
    for col1, row1, col2, row2, field_name, fallback in HEADER_IMAGE_SLOTS:
        source = getattr(torneo, field_name, None) if torneo else None
        sources.append((col1, row1, col2, row2, source or fallback))
    return sources


def _label_value(draw, label_cols, row, value_cols, label, value):
    _cell(draw, label_cols[0], row, label_cols[1], row, text=label, fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    _cell(draw, value_cols[0], row, value_cols[1], row, text=value, font=FONT_SMALL_BOLD, align="left", width=2)


def _draw_fecha_hora(draw, partido):
    x1, y1, x2, y2 = _box(15, 6, 25, 6)
    total_w = x2 - x1
    widths = [total_w * 0.17, total_w * 0.43, total_w * 0.15, total_w * 0.25]
    labels = [
        ("FECHA", FONT_SMALL_BOLD, "center", LIGHT),
        (_fecha_con_dia(partido.fecha), FONT_TINY_BOLD, "left", WHITE),
        ("HORA", FONT_SMALL_BOLD, "center", LIGHT),
        (_hora(partido.hora), FONT_TINY_BOLD, "left", WHITE),
    ]
    current = x1
    for width, (text, font, align, fill) in zip(widths, labels):
        box = [current, y1, current + width, y2]
        draw.rectangle(box, outline=BORDER, width=2, fill=fill)
        _text(draw, box, text, font=font, align=align)
        current += width


def _jugadores(equipo):
    return list(equipo.jugadores.filter(estado="ACTIVO").order_by("dorsal", "nombres"))[:30]


def _draw_player_side(img, draw, start_col, team_title, jugadores, referencia, equipo=None):
    name_start = start_col + 1
    if start_col == 1:
        name_end = 6
        number_col, edad_col, inic_col, sup_col, amarilla_cols, roja_col = 7, 8, 9, 10, (11, 12), 13
    else:
        name_end = 20
        number_col, edad_col, inic_col, sup_col, amarilla_cols, roja_col = 21, 22, 23, 24, (25, 26), 27

    _cell(draw, start_col, 10, start_col + 12, 10, team_title, fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    _cell(draw, amarilla_cols[0], 10, roja_col, 10, "Tarjetas", fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    _cell(draw, start_col, 11, text="N°", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, name_start, 11, name_end, 11, "NOMBRE Y APELLIDOS", fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    _cell(draw, number_col, 11, text="#", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, edad_col, 11, fill=LIGHT, width=2)
    _vertical_text(img, _box(edad_col, 11, edad_col, 11), "EDAD")
    _cell(draw, inic_col, 11, fill=LIGHT, width=2)
    _vertical_text(img, _box(inic_col, 11, inic_col, 11), "INICIA")
    _cell(draw, sup_col, 11, fill=LIGHT, width=2)
    _vertical_text(img, _box(sup_col, 11, sup_col, 11), "SUPLE")
    _cell(draw, amarilla_cols[0], 11, amarilla_cols[1], 11, "A", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, roja_col, 11, text="R", fill=LIGHT, font=FONT_TINY_BOLD, width=2)

    row_cells = [
        (start_col, start_col),
        (name_start, name_end),
        (number_col, number_col),
        (edad_col, edad_col),
        (inic_col, inic_col),
        (sup_col, sup_col),
        (amarilla_cols[0], amarilla_cols[0]),
        (amarilla_cols[1], amarilla_cols[1]),
        (roja_col, roja_col),
    ]

    for index in range(30):
        row = 12 + index
        for col1, col2 in row_cells:
            _cell(draw, col1, row, col2, row, text="", font=FONT_TINY)

    _draw_team_watermark(img, equipo, _box(start_col, 12, start_col + 12, 41))

    for index in range(30):
        row = 12 + index
        for col1, col2 in row_cells:
            draw.rectangle(_box(col1, row, col2, row), outline=BORDER, width=1)

        jugador = jugadores[index] if index < len(jugadores) else None
        nombre = _clean(getattr(jugador, "nombres", "")).title() if jugador else ""
        if jugador and getattr(jugador, "es_foraneo", False):
            nombre = f"{nombre} (F)"
        _text(draw, _box(start_col, row, start_col, row), str(index + 1), font=FONT_TINY)
        _text(draw, _box(name_start, row, name_end, row), nombre, font=FONT_SMALL, align="left")
        _text(draw, _box(number_col, row, number_col, row), _dorsal(getattr(jugador, "dorsal", "")) if jugador else "", font=FONT_TINY)
        _text(draw, _box(edad_col, row, edad_col, row), _edad(getattr(jugador, "fecha_nacimiento", None), referencia) if jugador else "", font=FONT_TINY)


def _draw_changes(draw, col1, col2):
    _cell(draw, col1, 42, col2, 42, "CONTROL DE CAMBIOS", fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    side_x1, _, side_x2, _ = _box(col1, 43, col2, 49)
    side_w = side_x2 - side_x1
    margin = side_w * 0.055
    gap = side_w * 0.085
    block_w = (side_w - (margin * 2) - (gap * 2)) / 3
    header_y1 = Y[42]
    header_y2 = Y[43]
    bottom_y = Y[49]
    labels = ["E", "S", "MIN"]

    for index in range(3):
        x1 = side_x1 + margin + index * (block_w + gap)
        x2 = x1 + block_w
        cell_w = block_w / 3
        draw.rectangle([x1, header_y1, x2, bottom_y], outline=BORDER, width=2, fill=WHITE)

        for col_index, label in enumerate(labels):
            cx1 = x1 + col_index * cell_w
            cx2 = cx1 + cell_w
            draw.rectangle([cx1, header_y1, cx2, header_y2], outline=BORDER, width=1, fill=LIGHT)
            _text(draw, [cx1, header_y1, cx2, header_y2], label, font=FONT_TINY_BOLD)
            for row in range(44, 50):
                draw.rectangle([cx1, Y[row - 1], cx2, Y[row]], outline=BORDER, width=1, fill=WHITE)


def _draw_goals(draw, col1, col2):
    _cell(draw, col1 + 1, 50, col2 - 1, 50, "GOLES", fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    side_x1, _, side_x2, _ = _box(col1 + 1, 51, col2 - 1, 54)
    cell_w = (side_x2 - side_x1) / 6
    goal = 1
    for row_label, row_number in [(51, 52), (53, 54)]:
        for index in range(6):
            x1 = side_x1 + index * cell_w
            x2 = x1 + cell_w
            label_box = [x1, Y[row_label - 1], x2, Y[row_label]]
            number_box = [x1, Y[row_number - 1], x2, Y[row_number]]
            draw.rectangle(label_box, outline=BORDER, width=1, fill=LIGHT)
            _text(draw, label_box, f"GOL {goal}", font=FONT_TINY_BOLD)
            draw.rectangle(number_box, outline=BORDER, width=1, fill=WHITE)
            _text(draw, number_box, "#", font=FONT_SMALL_BOLD, align="left")
            goal += 1


def generar_planilla_juego_pdf(partido):
    img = Image.new("RGB", (PAGE_W, PAGE_H), WHITE)
    draw = ImageDraw.Draw(img)

    for col1, row1, col2, row2, source in _header_image_sources(partido):
        if not source:
            continue
        _cell(draw, col1, row1, col2, row2, fill=WHITE, width=2)
        _draw_image_fit(img, source, _box(col1, row1, col2, row2))

    _cell(draw, 1, 5, 27, 5, _titulo_planilla(partido), fill=WHITE, font=FONT_TITLE, width=2)

    _label_value(draw, (1, 4), 6, (5, 11), "FECHAS:", _fase(partido))
    _draw_fecha_hora(draw, partido)
    _label_value(draw, (1, 4), 7, (5, 11), "CATEGORIA", partido.categoria.nombre.upper())
    _label_value(draw, (15, 17), 7, (18, 25), "ARBITRO", "")
    _label_value(draw, (1, 4), 8, (5, 11), "CANCHA", _clean(partido.cancha, "").upper())
    _label_value(draw, (15, 17), 8, (18, 25), "MARCADOR", "")
    _label_value(draw, (1, 4), 9, (5, 11), "Equipo A:", partido.equipo_local.nombre.upper())
    _label_value(draw, (15, 17), 9, (18, 25), "Equipo B:", partido.equipo_visitante.nombre.upper())
    _draw_team_shield(img, draw, partido.equipo_local, 12, 6, 13, 9)
    _draw_team_shield(img, draw, partido.equipo_visitante, 26, 6, 27, 9)

    referencia = partido.fecha or date.today()
    _draw_player_side(img, draw, 1, "LISTADO DE JUGADORES - EQUIPO A", _jugadores(partido.equipo_local), referencia, partido.equipo_local)
    _draw_player_side(img, draw, 15, "LISTADO DE JUGADORES - EQUIPO B", _jugadores(partido.equipo_visitante), referencia, partido.equipo_visitante)

    _draw_changes(draw, 1, 13)
    _draw_changes(draw, 15, 27)
    _draw_goals(draw, 1, 13)
    _draw_goals(draw, 15, 27)

    _cell(draw, 1, 55, 27, 58, "COMENTARIOS DEL ARBITRO:", font=FONT_SMALL_BOLD, align="left", valign="top", width=2)
    _cell(draw, 1, 59, 27, 59, "FIRMA ARBITRO CENTRAL:", font=FONT_SMALL_BOLD, align="left", width=2)

    output = BytesIO()
    img.save(output, format="PDF", resolution=PDF_DPI)
    return output.getvalue()
