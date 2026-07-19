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
    limpio = texto_limpio(valor)
    return " ".join(limpio.split()[:3])
