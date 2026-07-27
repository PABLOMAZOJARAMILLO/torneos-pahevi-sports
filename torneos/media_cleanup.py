from django.apps import apps
from django.core.files.storage import default_storage
from django.db import models, transaction


EXTENSIONES_IMAGEN = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
)


def nombres_imagenes_instancias(instancias):
    nombres = set()
    for instancia in instancias:
        for campo in instancia._meta.get_fields():
            if not isinstance(campo, models.ImageField):
                continue
            archivo = getattr(instancia, campo.name, None)
            nombre = str(getattr(archivo, "name", "") or "").strip()
            if nombre:
                nombres.add(nombre)
    return nombres


def _variantes_referencia(nombre, storage):
    nombre = str(nombre or "").replace("\\", "/").lstrip("/")
    variantes = {nombre}

    normalizar = getattr(storage, "_public_id", None)
    if callable(normalizar):
        public_id = normalizar(nombre)
        variantes.add(public_id)
        variantes.update(f"{public_id}{extension}" for extension in EXTENSIONES_IMAGEN)

    return variantes


def imagen_sigue_referenciada(nombre, storage=None):
    storage = storage or default_storage
    variantes = _variantes_referencia(nombre, storage)

    for modelo in apps.get_models():
        for campo in modelo._meta.get_fields():
            if not isinstance(campo, models.ImageField):
                continue
            if modelo._default_manager.filter(**{f"{campo.name}__in": variantes}).exists():
                return True
    return False


def eliminar_imagenes_sin_referencia(nombres, storage=None):
    storage = storage or default_storage
    eliminadas = []

    for nombre in sorted(set(nombres)):
        if imagen_sigue_referenciada(nombre, storage=storage):
            continue
        storage.delete(nombre)
        eliminadas.append(nombre)

    return eliminadas


def programar_limpieza_imagenes(nombres):
    nombres = tuple(sorted(set(nombres)))
    if not nombres:
        return
    transaction.on_commit(lambda: eliminar_imagenes_sin_referencia(nombres))
