from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from django.utils.text import slugify

PAGE_W = 2148
PAGE_H = 3038
PDF_DPI = 200
MARGIN_X = 70
MARGIN_Y = 80

BLACK = "#111111"
BORDER = "#111111"
LIGHT = "#F2F2F2"
WHITE = "#FFFFFF"

COL_WIDTHS = [
    4.0, 5.83203125, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0,
    13.0, 13.0, 13.0, 4.0, 3.5, 4.0, 5.83203125, 13.0, 13.0,
    13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 6.0, 4.0,
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
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ])
    candidates.extend([
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
    ])
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


FONT_TITLE = _font(30, True)
FONT_HEAD = _font(21, True)
FONT_NORMAL = _font(19)
FONT_SMALL = _font(18)
FONT_SMALL_BOLD = _font(18, True)
FONT_TINY = _font(16)
FONT_TINY_BOLD = _font(16, True)

STATIC_IMG_DIR = Path(__file__).resolve().parent / "static" / "torneos" / "img"
HEADER_IMAGES = [
    (1, 1, 7, 4, STATIC_IMG_DIR / "planilla_header_left.png"),
    (8, 1, 17, 4, STATIC_IMG_DIR / "planilla_header_center.png"),
    (18, 1, 27, 4, STATIC_IMG_DIR / "planilla_header_right.png"),
]


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
    return value.strftime("%I:%M:%S %p").lower().replace("am", "a. m.").replace("pm", "p. m.")


def _edad(fecha_nacimiento, referencia=None):
    if not fecha_nacimiento:
        return ""
    referencia = referencia or date.today()
    return str(
        referencia.year
        - fecha_nacimiento.year
        - ((referencia.month, referencia.day) < (fecha_nacimiento.month, fecha_nacimiento.day))
    )


def _fase(partido):
    if partido.fase == "GRUPOS":
        return _clean(partido.numero_fecha, "FECHA")
    return partido.get_fase_display().upper()


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


def _cell(draw, col1, row1, col2=None, row2=None, text="", fill=WHITE, font=FONT_SMALL, align="center", width=1):
    col2 = col2 or col1
    row2 = row2 or row1
    box = _box(col1, row1, col2, row2)
    draw.rectangle(box, outline=BORDER, width=width, fill=fill)
    if text not in (None, ""):
        _text(draw, box, text, font=font, align=align)


def _draw_image_fit(base, path, box):
    if not path.exists():
        return
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    with Image.open(path) as image:
        image = image.convert("RGBA")
        image.thumbnail((max(1, x2 - x1 - 8), max(1, y2 - y1 - 8)), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (x2 - x1, y2 - y1), (255, 255, 255, 255))
        canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2), image)
        base.paste(canvas.convert("RGB"), (x1, y1))


def _label_value(draw, label_cols, row, value_cols, label, value):
    _cell(draw, label_cols[0], row, label_cols[1], row, text=label, fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    _cell(draw, value_cols[0], row, value_cols[1], row, text=value, font=FONT_SMALL_BOLD, align="left", width=2)


def _jugadores(equipo):
    return list(equipo.jugadores.filter(estado="ACTIVO").order_by("dorsal", "nombres"))[:30]


def _draw_player_side(draw, start_col, team_title, jugadores, referencia):
    name_start = start_col + 1
    if start_col == 1:
        name_end = 7
        number_col, edad_col, inic_col, sup_col, amarilla_col, roja_col = 8, 9, 10, 11, 12, 13
    else:
        name_end = 21
        number_col, edad_col, inic_col, sup_col, amarilla_col, roja_col = 22, 23, 24, 25, 26, 27

    _cell(draw, start_col, 10, start_col + 12, 10, team_title, fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    _cell(draw, start_col + 11, 10, start_col + 12, 10, "Tarjetas", fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    _cell(draw, start_col, 11, text="No", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, name_start, 11, name_end, 11, "NOMBRE Y APELLIDOS", fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    _cell(draw, number_col, 11, text="#", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, edad_col, 11, text="EDAD", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, inic_col, 11, text="INIC", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, sup_col, 11, text="SUP", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, amarilla_col, 11, text="A", fill=LIGHT, font=FONT_TINY_BOLD, width=2)
    _cell(draw, roja_col, 11, text="R", fill=LIGHT, font=FONT_TINY_BOLD, width=2)

    for index in range(30):
        row = 12 + index
        jugador = jugadores[index] if index < len(jugadores) else None
        _cell(draw, start_col, row, text=str(index + 1), font=FONT_TINY)
        _cell(
            draw,
            name_start,
            row,
            name_end,
            row,
            _clean(getattr(jugador, "nombres", "")).title() if jugador else "",
            font=FONT_SMALL,
            align="left",
        )
        _cell(draw, number_col, row, text=_clean(getattr(jugador, "dorsal", "")) if jugador else "", font=FONT_TINY)
        _cell(draw, edad_col, row, text=_edad(getattr(jugador, "fecha_nacimiento", None), referencia) if jugador else "", font=FONT_TINY)
        _cell(draw, inic_col, row, text="", font=FONT_TINY)
        _cell(draw, sup_col, row, text="", font=FONT_TINY)
        _cell(draw, amarilla_col, row, text="", font=FONT_TINY)
        _cell(draw, roja_col, row, text="", font=FONT_TINY)


def _draw_changes(draw, col1, col2):
    _cell(draw, col1, 42, col2, 42, "CONTROL DE CAMBIOS", fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    groups = [(col1 + 1, col1 + 3), (col1 + 5, col1 + 7), (col1 + 9, col1 + 11)]
    for group in groups:
        for col, label in zip(group, ["E", "S", "MIN"]):
            _cell(draw, col, 43, text=label, fill=LIGHT, font=FONT_TINY_BOLD, width=2)
            for row in range(44, 50):
                _cell(draw, col, row)


def _draw_goals(draw, col1, col2):
    _cell(draw, col1 + 1, 50, col2 - 1, 50, "GOLES", fill=LIGHT, font=FONT_SMALL_BOLD, width=2)
    goal = 1
    for row_label, row_number in [(51, 52), (53, 54)]:
        for col in range(col1 + 1, col2, 2):
            _cell(draw, col, row_label, col + 1, row_label, f"GOL {goal}", fill=LIGHT, font=FONT_TINY_BOLD)
            _cell(draw, col, row_number, col + 1, row_number, "#", font=FONT_SMALL_BOLD)
            goal += 1
    _cell(draw, col1 + 1, 55, col2 - 1, 58, "")


def generar_planilla_juego_pdf(partido):
    img = Image.new("RGB", (PAGE_W, PAGE_H), WHITE)
    draw = ImageDraw.Draw(img)

    for col1, row1, col2, row2, path in HEADER_IMAGES:
        _cell(draw, col1, row1, col2, row2, fill=WHITE, width=2)
        _draw_image_fit(img, path, _box(col1, row1, col2, row2))

    _cell(draw, 1, 5, 27, 5, "PLANILLA DE JUEGO TORNEO VERANERO: SENIOR MASTER, PLUS 50 E INTERBARRIOS", fill=WHITE, font=FONT_TITLE, width=2)

    _label_value(draw, (1, 4), 6, (5, 13), "FECHAS:", _fase(partido))
    _label_value(draw, (15, 17), 6, (18, 21), "FECHA", _fecha(partido.fecha))
    _label_value(draw, (22, 23), 6, (24, 27), "HORA", _hora(partido.hora))
    _label_value(draw, (1, 4), 7, (5, 13), "CATEGORIA", partido.categoria.nombre.upper())
    _label_value(draw, (15, 17), 7, (18, 27), "ARBITRO", "")
    _label_value(draw, (1, 4), 8, (5, 13), "CANCHA", _clean(partido.cancha, "").upper())
    _label_value(draw, (15, 17), 8, (18, 27), "MARCADOR", "")
    _label_value(draw, (1, 4), 9, (5, 13), "Equipo A:", partido.equipo_local.nombre.upper())
    _label_value(draw, (15, 17), 9, (18, 27), "Equipo B:", partido.equipo_visitante.nombre.upper())

    referencia = partido.fecha or date.today()
    _draw_player_side(draw, 1, "LISTADO DE JUGADORES - EQUIPO A", _jugadores(partido.equipo_local), referencia)
    _draw_player_side(draw, 15, "LISTADO DE JUGADORES - EQUIPO B", _jugadores(partido.equipo_visitante), referencia)

    _draw_changes(draw, 1, 13)
    _draw_changes(draw, 15, 27)
    _draw_goals(draw, 1, 13)
    _draw_goals(draw, 15, 27)

    _cell(draw, 2, 59, 13, 59, "Firma Delegado Equipo A: ", font=FONT_SMALL_BOLD, align="left", width=2)
    _cell(draw, 15, 59, 26, 59, "Firma Delegado Equipo B:", font=FONT_SMALL_BOLD, align="left", width=2)

    output = BytesIO()
    img.save(output, format="PDF", resolution=PDF_DPI)
    return output.getvalue()
