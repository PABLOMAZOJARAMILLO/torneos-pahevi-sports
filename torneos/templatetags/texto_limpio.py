from django import template

register = template.Library()


MOJIBAKE_DOS = str.maketrans({
    "┴": "Á",
    "╡": "Á",
    "┐": "Á",
    "╔": "É",
    "╓": "Í",
    "═": "Í",
    "α": "Ó",
    "Θ": "Ú",
})


@register.filter
def texto_limpio(valor):
    if valor is None:
        return ""
    return str(valor).translate(MOJIBAKE_DOS)
