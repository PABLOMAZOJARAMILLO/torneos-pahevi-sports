import os
import re

from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError


def limpiar_ruta_cloudinary(valor):
    valor = str(valor or "").strip().upper()
    valor = re.sub(r'[\\/*?:"<>|#%&{}$!@+=`~]', '', valor)
    valor = re.sub(r'\s+', '_', valor)
    return valor or "SIN_NOMBRE"


def extension_archivo(nombre_archivo):
    _, extension = os.path.splitext(nombre_archivo or "")
    return extension.lower() or ".jpg"


def ruta_escudo_equipo(instance, filename):
    categoria = limpiar_ruta_cloudinary(getattr(instance.categoria, "nombre", "SIN_CATEGORIA"))
    equipo = limpiar_ruta_cloudinary(instance.nombre)
    return f"equipos/{categoria}/{equipo}/escudo{extension_archivo(filename)}"


def ruta_foto_jugador(instance, filename):
    equipo = instance.equipo
    categoria = limpiar_ruta_cloudinary(getattr(equipo.categoria, "nombre", "SIN_CATEGORIA"))
    equipo_nombre = limpiar_ruta_cloudinary(getattr(equipo, "nombre", "SIN_EQUIPO"))
    jugador = limpiar_ruta_cloudinary(instance.cedula or instance.nombres)
    return f"jugadores/{categoria}/{equipo_nombre}/{jugador}{extension_archivo(filename)}"


def ruta_documento(instance, filename):
    tipo = limpiar_ruta_cloudinary(instance.tipo)
    titulo = limpiar_ruta_cloudinary(instance.titulo)
    return f"documentos/{tipo}/{titulo}{extension_archivo(filename)}"


def ruta_logo_portada_torneo(instance, filename):
    torneo = limpiar_ruta_cloudinary(instance.nombre)
    return f"torneos/{torneo}/logo_portada{extension_archivo(filename)}"


def ruta_logo_izquierdo_torneo(instance, filename):
    torneo = limpiar_ruta_cloudinary(instance.nombre)
    return f"torneos/{torneo}/logo_izquierdo{extension_archivo(filename)}"


def ruta_imagen_central_torneo(instance, filename):
    torneo = limpiar_ruta_cloudinary(instance.nombre)
    return f"torneos/{torneo}/imagen_central{extension_archivo(filename)}"


def ruta_logo_derecho_torneo(instance, filename):
    torneo = limpiar_ruta_cloudinary(instance.nombre)
    return f"torneos/{torneo}/logo_derecho{extension_archivo(filename)}"


def ruta_logo_organizador(instance, filename):
    organizador = limpiar_ruta_cloudinary(instance.nombre)
    return f"organizadores/{organizador}/logo{extension_archivo(filename)}"


def ruta_portada_organizador(instance, filename):
    organizador = limpiar_ruta_cloudinary(instance.nombre)
    return f"organizadores/{organizador}/portada{extension_archivo(filename)}"


class Organizador(models.Model):
    nombre = models.CharField(max_length=150, unique=True, verbose_name='Nombre del organizador')
    descripcion = models.TextField(blank=True, null=True, verbose_name='DescripciÃ³n')
    logo = models.ImageField(upload_to=ruta_logo_organizador, blank=True, null=True, verbose_name='Logo del organizador')
    portada = models.ImageField(upload_to=ruta_portada_organizador, blank=True, null=True, verbose_name='Portada del organizador')
    activo = models.BooleanField(default=True, verbose_name='Activo')
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name='Creado en')

    class Meta:
        verbose_name = 'Organizador'
        verbose_name_plural = 'Organizadores'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Torneo(models.Model):
    ESTADOS = [
        ('ACTIVO', 'Activo'),
        ('FINALIZADO', 'Finalizado'),
        ('SUSPENDIDO', 'Suspendido'),
    ]

    nombre = models.CharField(max_length=150, verbose_name='Nombre del torneo')
    organizador = models.ForeignKey(Organizador, on_delete=models.SET_NULL, blank=True, null=True, related_name='torneos', verbose_name='Organizador')
    descripcion = models.TextField(blank=True, null=True, verbose_name='Descripción')
    lema = models.CharField(max_length=180, blank=True, null=True, verbose_name='Lema')
    logo_portada = models.ImageField(upload_to=ruta_logo_portada_torneo, blank=True, null=True, verbose_name='Logo de portada')
    logo_izquierdo = models.ImageField(upload_to=ruta_logo_izquierdo_torneo, blank=True, null=True, verbose_name='Logo izquierdo del encabezado')
    imagen_central = models.ImageField(upload_to=ruta_imagen_central_torneo, blank=True, null=True, verbose_name='Imagen central del encabezado')
    logo_derecho = models.ImageField(upload_to=ruta_logo_derecho_torneo, blank=True, null=True, verbose_name='Logo derecho del encabezado')
    fecha_inicio = models.DateField(verbose_name='Fecha de inicio')
    fecha_fin = models.DateField(blank=True, null=True, verbose_name='Fecha de finalización')
    estado = models.CharField(max_length=20, choices=ESTADOS, default='ACTIVO', verbose_name='Estado')
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name='Creado en')

    class Meta:
        verbose_name = 'Torneo'
        verbose_name_plural = 'Torneos'
        ordering = ['-fecha_inicio']

    def __str__(self):
        return self.nombre


class Categoria(models.Model):
    nombre = models.CharField(max_length=100, verbose_name='Nombre de la categoría')
    descripcion = models.TextField(blank=True, null=True, verbose_name='Descripción')
    edad_minima = models.IntegerField(verbose_name='Edad mínima')
    edad_maxima = models.IntegerField(verbose_name='Edad máxima')
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name='categorias', blank=True, null=True)
    controlar_foraneos = models.BooleanField(default=False, verbose_name='Controlar foráneos')
    porcentaje_minimo_foraneos = models.PositiveIntegerField(default=50, verbose_name='Porcentaje mínimo fase 1 foráneos')

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'

    def __str__(self):
        if self.torneo:
            return f"{self.nombre} - {self.torneo.nombre}"
        return self.nombre


class ReglaEdadCategoria(models.Model):
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='reglas_edad')
    etiqueta = models.CharField(max_length=20, verbose_name='Etiqueta')
    edad_minima = models.PositiveIntegerField(verbose_name='Edad minima')
    edad_maxima = models.PositiveIntegerField(blank=True, null=True, verbose_name='Edad maxima')
    minimo_titulares = models.PositiveIntegerField(default=0, verbose_name='Minimo en cancha')
    orden = models.PositiveIntegerField(default=0)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Regla de edad'
        verbose_name_plural = 'Reglas de edad'
        ordering = ['categoria__nombre', 'orden', 'edad_minima']

    def __str__(self):
        maximo = self.edad_maxima if self.edad_maxima is not None else '+'
        return f"{self.categoria.nombre} - {self.etiqueta} ({self.edad_minima}-{maximo})"

    def clean(self):
        super().clean()
        if self.edad_maxima is not None and self.edad_maxima < self.edad_minima:
            raise ValidationError({"edad_maxima": "La edad maxima no puede ser menor que la edad minima."})

    def coincide_con_edad(self, edad):
        if edad is None or edad < self.edad_minima:
            return False
        return self.edad_maxima is None or edad <= self.edad_maxima


class Documento(models.Model):
    TIPOS = [
        ("REGLAMENTO", "Reglamento"),
        ("RESOLUCION", "Resolución"),
        ("DEMANDA", "Demanda"),
        ("COMUNICADO", "Comunicado"),
    ]

    tipo = models.CharField(max_length=20, choices=TIPOS, verbose_name="Tipo")
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name="documentos", blank=True, null=True)
    titulo = models.CharField(max_length=180, verbose_name="Título")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    archivo = models.URLField(max_length=600, verbose_name="Archivo")
    activo = models.BooleanField(default=True, verbose_name="Activo")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Creado en")

    class Meta:
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"
        ordering = ["tipo", "-creado_en", "titulo"]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.titulo}"


class Equipo(models.Model):
    nombre = models.CharField(max_length=120, verbose_name='Nombre del equipo')
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='equipos')
    responsable = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='equipos_asignados', verbose_name='Usuario responsable')
    delegado = models.CharField(max_length=120, blank=True, null=True, verbose_name='Delegado')
    telefono = models.CharField(max_length=30, blank=True, null=True, verbose_name='Celular delegado')
    director_tecnico = models.CharField(max_length=150, blank=True, null=True, verbose_name='Director técnico')
    telefono_dt = models.CharField(max_length=30, blank=True, null=True, verbose_name='Celular DT')
    asistente_tecnico = models.CharField(max_length=150, blank=True, null=True, verbose_name='Asistente técnico')
    telefono_at = models.CharField(max_length=30, blank=True, null=True, verbose_name='Celular AT')
    escudo = models.ImageField(upload_to=ruta_escudo_equipo, blank=True, null=True, verbose_name='Escudo')
    activo = models.BooleanField(default=True, verbose_name='Activo')

    class Meta:
        verbose_name = 'Equipo'
        verbose_name_plural = 'Equipos'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Jugador(models.Model):
    ESTADOS = [
        ('ACTIVO', 'Activo'),
        ('SUSPENDIDO', 'Suspendido'),
        ('RETIRADO', 'Retirado'),
    ]

    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='jugadores')
    dorsal = models.PositiveIntegerField(blank=True, null=True, verbose_name='Dorsal')
    nombres = models.CharField(max_length=150, verbose_name='Nombres y apellidos')
    cedula = models.CharField(max_length=30, verbose_name='Cédula')
    fecha_nacimiento = models.DateField(verbose_name='Fecha de nacimiento')
    telefono = models.CharField(max_length=30, blank=True, null=True, verbose_name='Teléfono')
    estado = models.CharField(max_length=20, choices=ESTADOS, default='ACTIVO', verbose_name='Estado')
    foto = models.ImageField(upload_to=ruta_foto_jugador, blank=True, null=True, verbose_name='Foto')
    es_foraneo = models.BooleanField(default=False, verbose_name='Foráneo')

    class Meta:
        verbose_name = 'Jugador'
        verbose_name_plural = 'Jugadores'
        ordering = ['nombres']
        constraints = [
            models.UniqueConstraint(fields=['equipo', 'cedula'], name='jugador_unico_por_equipo_cedula')
        ]

    def clean(self):
        super().clean()
        if not self.cedula or not self.equipo_id:
            return

        categoria_id = getattr(self.equipo, "categoria_id", None)
        if not categoria_id:
            return

        duplicado = Jugador.objects.filter(
            cedula=self.cedula,
            equipo__categoria_id=categoria_id,
        ).exclude(pk=self.pk).first()

        if duplicado:
            raise ValidationError({
                "cedula": (
                    f"Esta cedula ya esta registrada en {duplicado.equipo.nombre} "
                    f"para la categoria {duplicado.equipo.categoria.nombre}."
                )
            })

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nombres


class Partido(models.Model):
    ESTADOS = [
        ('PROGRAMADO', 'Programado'),
        ('EN_JUEGO', 'En juego'),
        ('FINALIZADO', 'Finalizado'),
        ('APLAZADO', 'Aplazado'),
        ('SUSPENDIDO', 'Suspendido'),
        ('WO', 'W.O.'),
        ('DECIDIDO_COMITE', 'Decidido por comité'),
    ]

    FASES = [
        ('GRUPOS', 'Fase de grupos'),
        ('CUARTOS', 'Cuartos de final'),
        ('SEMIFINAL', 'Semifinal'),
        ('FINAL', 'Final'),
        ('TERCER_PUESTO', 'Tercer puesto'),
    ]

    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    equipo_local = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='partidos_local')
    equipo_visitante = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='partidos_visitante')
    fecha = models.DateField()
    hora = models.TimeField()
    goles_local = models.IntegerField(default=0)
    goles_visitante = models.IntegerField(default=0)
    estado = models.CharField(max_length=30, choices=ESTADOS, default='PROGRAMADO')
    inicio_en_vivo = models.DateTimeField(blank=True, null=True, verbose_name="Inicio real en vivo")
    observaciones = models.TextField(blank=True, null=True)
    numero_fecha = models.CharField(max_length=50, blank=True, null=True, verbose_name='Fecha del fixture')
    grupo = models.CharField(max_length=20, blank=True, null=True, verbose_name='Grupo')
    cancha = models.CharField(max_length=100, blank=True, null=True, verbose_name='Cancha')
    fase = models.CharField(max_length=20, choices=FASES, default='GRUPOS', verbose_name='Fase')
    ajuste_puntos_local = models.IntegerField(default=0, verbose_name='Ajuste puntos local')
    ajuste_puntos_visitante = models.IntegerField(default=0, verbose_name='Ajuste puntos visitante')
    observacion_comite = models.TextField(blank=True, null=True, verbose_name='Observación del comité')
    goles_local_penales = models.IntegerField(default=0, blank=True, null=True)
    goles_visitante_penales = models.IntegerField(default=0, blank=True, null=True)
    siguiente_partido = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, related_name='partidos_origen', verbose_name='Partido siguiente')
    slot_siguiente = models.CharField(max_length=20, choices=(('LOCAL', 'Local'), ('VISITANTE', 'Visitante')), blank=True, null=True, verbose_name='Entra como')
    inicio_en_vivo = models.DateTimeField(blank=True, null=True, verbose_name="Inicio real en vivo")
    cronometro_pausado = models.BooleanField(default=False, verbose_name="Cronómetro pausado")   
    segundos_acumulados = models.PositiveIntegerField(default=0, verbose_name="Segundos acumulados")
    PERIODOS_PARTIDO = [
    ("PT", "Primer tiempo"),
    ("ET", "Entretiempo"),
    ("ST", "Segundo tiempo"),
    ("FIN", "Finalizado"),
    ]   
    inicio_en_vivo = models.DateTimeField(blank=True, null=True)
    cronometro_pausado = models.BooleanField(default=False)
    segundos_acumulados = models.PositiveIntegerField(default=0)
    periodo_en_vivo = models.CharField(
    max_length=5,
    choices=PERIODOS_PARTIDO,
    default="PT",
    blank=True)
    periodo_en_vivo = models.CharField(max_length=5, choices=PERIODOS_PARTIDO, default="PT", blank=True)

    class Meta:
        verbose_name = 'Partido'
        verbose_name_plural = 'Partidos'
        ordering = ['categoria__nombre', 'grupo', 'numero_fecha', 'fecha', 'hora']

    def __str__(self):
        return f"{self.equipo_local} vs {self.equipo_visitante}"


class Gol(models.Model):
    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='goles')
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='goles_registrados')
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField(default=1)
    es_autogol = models.BooleanField(default=False, verbose_name='Autogol')
    es_penal = models.BooleanField(default=False, verbose_name='Gol de penal')
    minuto = models.PositiveIntegerField(blank=True, null=True, verbose_name='Minuto')
    creado_en = models.DateTimeField(auto_now_add=True, blank=True, null=True, verbose_name='Creado en')

    class Meta:
        verbose_name = 'Gol'
        verbose_name_plural = 'Goles'

    def __str__(self):
        return f"{self.jugador} - {self.cantidad} gol(es)"


class Tarjeta(models.Model):
    TIPOS = [('AMARILLA', 'Amarilla'), ('ROJA', 'Roja')]
    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='tarjetas')
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='tarjetas_recibidas')
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    minuto = models.PositiveIntegerField(blank=True, null=True, verbose_name='Minuto')
    creado_en = models.DateTimeField(auto_now_add=True, blank=True, null=True, verbose_name='Creado en')

    class Meta:
        verbose_name = 'Tarjeta'
        verbose_name_plural = 'Tarjetas'

    def __str__(self):
        return f"{self.jugador} - {self.tipo}"


class EventoPartido(models.Model):
    TIPO_EVENTO = [('GOL', 'Gol'), ('A', 'Amarilla'), ('R', 'Roja')]
    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='eventos')
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='eventos')
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='eventos')
    tipo = models.CharField(max_length=10, choices=TIPO_EVENTO)

    class Meta:
        verbose_name = 'Evento del partido'
        verbose_name_plural = 'Eventos del partido'

    def __str__(self):
        return f"{self.jugador} - {self.tipo}"


class AlineacionPartido(models.Model):
    ROLES = [
        ('TITULAR', 'Titular'),
        ('SUPLENTE', 'Suplente'),
        ('NO_DISPONIBLE', 'No disponible'),
    ]
    POSICIONES_CANCHA = [
        ('POR', 'Arquero'),
        ('LI', 'Lateral izquierdo'),
        ('DFC1', 'Central izquierdo'),
        ('DFC2', 'Central derecho'),
        ('LD', 'Lateral derecho'),
        ('MC1', 'Medio izquierdo'),
        ('MC2', 'Medio centro'),
        ('MC3', 'Medio derecho'),
        ('EI', 'Extremo izquierdo'),
        ('DC', 'Delantero centro'),
        ('ED', 'Extremo derecho'),
    ]
    ORDEN_POSICIONES_CANCHA = {codigo: indice for indice, (codigo, _) in enumerate(POSICIONES_CANCHA)}

    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='alineaciones')
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='alineaciones_partido')
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='alineaciones_partido')
    rol = models.CharField(max_length=20, choices=ROLES, default='TITULAR')
    posicion_cancha = models.CharField(max_length=10, choices=POSICIONES_CANCHA, blank=True, default='', verbose_name='Posición en cancha')

    class Meta:
        verbose_name = 'Alineación del partido'
        verbose_name_plural = 'Alineaciones del partido'
        unique_together = ('partido', 'jugador')
        ordering = ['equipo__nombre', 'rol', 'jugador__nombres']

    def __str__(self):
        return f"{self.partido} - {self.jugador} ({self.rol})"


class SustitucionPartido(models.Model):
    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='sustituciones')
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='sustituciones_partido')
    jugador_sale = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='sustituciones_sale')
    jugador_entra = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='sustituciones_entra')
    minuto = models.PositiveIntegerField(blank=True, null=True)
    observacion = models.CharField(max_length=150, blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True, blank=True, null=True, verbose_name='Creado en')

    class Meta:
        verbose_name = 'Sustitución del partido'
        verbose_name_plural = 'Sustituciones del partido'
        ordering = ['equipo__nombre', 'minuto', 'id']

    def __str__(self):
        return f"{self.partido} - Sale {self.jugador_sale} / Entra {self.jugador_entra}"

