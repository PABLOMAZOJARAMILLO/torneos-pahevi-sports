import re
from datetime import datetime, time

from django import template

register = template.Library()


def _tabla_cp437_a_cp850():
    tabla = {}
    for codigo in range(128, 256):
        malo = bytes([codigo]).decode("cp437")
        bueno = bytes([codigo]).decode("cp850")
        if malo != bueno:
            tabla[ord(malo)] = bueno
    return tabla


MOJIBAKE_DOS = str.maketrans(_tabla_cp437_a_cp850())

MOJIBAKE_JUGADORES = str.maketrans({
    "\u2550": "\u00cd",
    "\u2553": "\u00cd",
    "\u2534": "\u00c1",
    "\u2561": "\u00c1",
    "\u2510": "\u00c1",
    "\u2554": "\u00c9",
    "\u03b1": "\u00d3",
    "\u0398": "\u00da",
    "\u00d0": "\u00d1",
})


@register.filter
def texto_limpio(valor):
    if valor is None:
        return ""
    return str(valor).translate(MOJIBAKE_DOS).translate(MOJIBAKE_JUGADORES)


@register.filter
def primeras_tres_palabras(valor):
    return nombre_corto(valor)


@register.filter
def nombre_corto(valor):
    limpio = texto_limpio(valor).strip()
    partes = [parte for parte in limpio.split() if parte]
    conectores = {"de", "del", "la", "las", "los", "da", "das", "do", "dos", "van", "von", "y"}
    if len(partes) >= 4:
        apellido = [partes[2]]
        indice = 3
        while apellido[-1].lower() in conectores and indice < len(partes):
            apellido.append(partes[indice])
            indice += 1
        return f"{partes[0]} {' '.join(apellido)}"
    if len(partes) >= 3:
        segundo = [partes[1]]
        indice = 2
        while segundo[-1].lower() in conectores and indice < len(partes):
            segundo.append(partes[indice])
            indice += 1
        return f"{partes[0]} {' '.join(segundo)}"
    return " ".join(partes) or "Jugador"


@register.filter
def etiqueta_fecha(valor):
    if valor is None:
        return ""
    texto = str(valor).strip()
    if re.fullmatch(r"\d+", texto):
        return f"Fecha {texto}"
    return texto


@register.filter
def fecha_en_titulo(valor):
    if valor is None:
        return ""
    return re.sub(r"(?<= - )(\d+)(?= - )", r"Fecha \1", str(valor))


@register.filter
def hora_12(valor):
    if valor in (None, ""):
        return ""
    hora = valor
    if isinstance(valor, str):
        texto = valor.strip()
        for formato in ("%H:%M:%S", "%H:%M"):
            try:
                hora = datetime.strptime(texto, formato).time()
                break
            except ValueError:
                continue
        else:
            return texto
    if isinstance(hora, (datetime, time)):
        return hora.strftime("%I:%M %p").lstrip("0")
    return str(valor)
