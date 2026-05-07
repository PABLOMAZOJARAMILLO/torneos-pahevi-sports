from django.db import models


class Torneo(models.Model):
    ESTADOS = [
        ('ACTIVO', 'Activo'),
        ('FINALIZADO', 'Finalizado'),
        ('SUSPENDIDO', 'Suspendido'),
    ]

    nombre = models.CharField(max_length=150, verbose_name='Nombre del torneo')
    descripcion = models.TextField(blank=True, null=True, verbose_name='Descripción')
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
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name='categorias')

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'

    def __str__(self):
        return f"{self.nombre} - {self.torneo.nombre}"


class Equipo(models.Model):
    nombre = models.CharField(max_length=120, verbose_name='Nombre del equipo')
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='equipos')
    delegado = models.CharField(max_length=120, blank=True, null=True, verbose_name='Delegado')
    telefono = models.CharField(max_length=30, blank=True, null=True, verbose_name='Teléfono')
    escudo = models.ImageField(upload_to='escudos/', blank=True, null=True, verbose_name='Escudo')
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
    cedula = models.CharField(max_length=30, unique=True, verbose_name='Cédula')
    fecha_nacimiento = models.DateField(verbose_name='Fecha de nacimiento')
    telefono = models.CharField(max_length=30, blank=True, null=True, verbose_name='Teléfono')
    estado = models.CharField(max_length=20, choices=ESTADOS, default='ACTIVO', verbose_name='Estado')
    foto = models.ImageField(upload_to='jugadores/', blank=True, null=True, verbose_name='Foto')

    class Meta:
        verbose_name = 'Jugador'
        verbose_name_plural = 'Jugadores'
        ordering = ['nombres']

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
        ("GRUPOS", "Fase de grupos"),
        ("CUARTOS", "Cuartos de final"),
        ("SEMIFINAL", "Semifinal"),
        ("FINAL", "Final"),
        ("TERCER_PUESTO", "Tercer puesto"),
    ]

    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    equipo_local = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='partidos_local')
    equipo_visitante = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='partidos_visitante')

    fecha = models.DateField()
    hora = models.TimeField()

    goles_local = models.IntegerField(default=0)
    goles_visitante = models.IntegerField(default=0)

    estado = models.CharField(max_length=30, choices=ESTADOS, default='PROGRAMADO')
    observaciones = models.TextField(blank=True, null=True)

    numero_fecha = models.CharField(max_length=50, blank=True, null=True, verbose_name='Fecha del fixture')
    grupo = models.CharField(max_length=20, blank=True, null=True, verbose_name='Grupo')
    cancha = models.CharField(max_length=100, blank=True, null=True, verbose_name='Cancha')

    fase = models.CharField(max_length=20, choices=FASES, default='GRUPOS', verbose_name='Fase')


    ajuste_puntos_local = models.IntegerField(
        default=0,
        verbose_name="Ajuste puntos local"
    )

    ajuste_puntos_visitante = models.IntegerField(
        default=0,
        verbose_name="Ajuste puntos visitante"
    )

    observacion_comite = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observación del comité"
    )
    goles_local_penales = models.IntegerField(default=0, blank=True, null=True)
    goles_visitante_penales = models.IntegerField(default=0, blank=True, null=True)

    siguiente_partido = models.ForeignKey(
    'self',
    on_delete=models.SET_NULL,
    blank=True,
    null=True,
    related_name='partidos_origen',
    verbose_name='Partido siguiente'
    )

    slot_siguiente = models.CharField(
    max_length=20,
    choices=(
        ('LOCAL', 'Local'),
        ('VISITANTE', 'Visitante'),
    ),
    blank=True,
    null=True,
    verbose_name='Entra como'
    )
    

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

    class Meta:
        verbose_name = 'Gol'
        verbose_name_plural = 'Goles'

    def __str__(self):
        return f"{self.jugador} - {self.cantidad} gol(es)"


class Tarjeta(models.Model):
    TIPOS = [
        ('AMARILLA', 'Amarilla'),
        ('ROJA', 'Roja'),
    ]

    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='tarjetas')
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='tarjetas_recibidas')
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE)
    tipo = models.CharField(max_length=20, choices=TIPOS)

    class Meta:
        verbose_name = 'Tarjeta'
        verbose_name_plural = 'Tarjetas'

    def __str__(self):
        return f"{self.jugador} - {self.tipo}"


class EventoPartido(models.Model):
    TIPO_EVENTO = [
        ('GOL', 'Gol'),
        ('A', 'Amarilla'),
        ('R', 'Roja'),
    ]

    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='eventos')
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='eventos')
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='eventos')
    tipo = models.CharField(max_length=10, choices=TIPO_EVENTO)

    class Meta:
        verbose_name = 'Evento del partido'
        verbose_name_plural = 'Eventos del partido'

    def __str__(self):
        return f"{self.jugador} - {self.tipo}"
    