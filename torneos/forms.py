from django import forms
from django.contrib.auth.models import User
from django.db.models import Q

from .models import Torneo, Organizador, Documento, Categoria, Equipo, Jugador, Partido, AdminTorneo, AdminOrganizador


class OrganizadorForm(forms.ModelForm):
    class Meta:
        model = Organizador
        fields = [
            "nombre",
            "descripcion",
            "logo",
            "portada",
            "activo",
        ]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 3}),
        }


class TorneoForm(forms.ModelForm):
    class Meta:
        model = Torneo
        fields = [
            "nombre",
            "organizador",
            "descripcion",
            "lema",
            "logo_portada",
            "logo_izquierdo",
            "imagen_central",
            "logo_derecho",
            "fecha_inicio",
            "fecha_fin",
            "estado",
        ]
        widgets = {
            "fecha_inicio": forms.DateInput(attrs={"type": "date"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date"}),
            "descripcion": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields.pop("fecha_inicio", None)
            self.fields.pop("fecha_fin", None)


class AdminTorneoForm(forms.ModelForm):
    class Meta:
        model = AdminTorneo
        fields = [
            "usuario",
            "puede_editar",
            "puede_validar",
            "puede_programar",
            "puede_descargar_planillas",
            "activo",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = self.fields["usuario"].queryset.filter(is_staff=True).order_by("username")
        self.fields["usuario"].label_from_instance = lambda obj: obj.get_full_name() or obj.username


class AdminOrganizadorForm(forms.ModelForm):
    class Meta:
        model = AdminOrganizador
        fields = [
            "usuario",
            "puede_editar",
            "puede_validar",
            "puede_programar",
            "puede_descargar_planillas",
            "activo",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = self.fields["usuario"].queryset.filter(is_staff=True).order_by("username")
        self.fields["usuario"].label_from_instance = lambda obj: obj.get_full_name() or obj.username


class CrearAdminOrganizadorForm(forms.Form):
    username = forms.CharField(label="Usuario", max_length=150)
    first_name = forms.CharField(label="Nombre", max_length=150, required=False)
    last_name = forms.CharField(label="Apellido", max_length=150, required=False)
    email = forms.EmailField(label="Correo", required=False)
    password = forms.CharField(label="Contraseña temporal", widget=forms.PasswordInput)
    puede_editar = forms.BooleanField(label="Puede editar", required=False, initial=True)
    puede_validar = forms.BooleanField(label="Puede validar", required=False, initial=True)
    puede_programar = forms.BooleanField(label="Puede programar", required=False, initial=True)
    puede_descargar_planillas = forms.BooleanField(label="Puede descargar planillas", required=False, initial=False)
    activo = forms.BooleanField(label="Activo", required=False, initial=True)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre. Usa el formulario de asignar admin existente.")
        return username

    def save_user(self):
        user = User(
            username=self.cleaned_data["username"],
            first_name=self.cleaned_data.get("first_name", ""),
            last_name=self.cleaned_data.get("last_name", ""),
            email=self.cleaned_data.get("email", ""),
            is_staff=True,
        )
        user.set_password(self.cleaned_data["password"])
        user.save()
        return user


class DocumentoForm(forms.ModelForm):
    archivo_subido = forms.FileField(label="Archivo", required=False)

    class Meta:
        model = Documento
        fields = [
            "torneo",
            "tipo",
            "titulo",
            "descripcion",
            "archivo_subido",
            "activo",
        ]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        torneo = kwargs.pop("torneo", None)
        super().__init__(*args, **kwargs)
        self.fields["tipo"].choices = [
            (valor, etiqueta)
            for valor, etiqueta in self.fields["tipo"].choices
            if valor != "PLANILLA_JUEGO"
        ]
        if torneo:
            self.fields["torneo"].queryset = Torneo.objects.filter(id=torneo.id)
            self.fields["torneo"].initial = torneo
        if not self.instance.pk:
            self.fields["archivo_subido"].required = True


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if isinstance(data, (list, tuple)):
            return [super(MultipleFileField, self).clean(archivo, initial) for archivo in data]
        if data:
            return [super().clean(data, initial)]
        return []


class PlanillaJuegoUploadForm(forms.Form):
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.none(),
        label="Categoria",
        empty_label="Selecciona la categoria",
    )
    numero_fecha = forms.ChoiceField(
        label="Fecha de programacion",
        required=False,
        choices=[],
    )
    equipo_local = forms.ModelChoiceField(
        queryset=Equipo.objects.none(),
        label="Equipo A",
        empty_label="Selecciona el equipo A",
    )
    equipo_visitante = forms.ModelChoiceField(
        queryset=Equipo.objects.none(),
        label="Equipo B",
        empty_label="Selecciona el equipo B",
    )
    fecha_partido = forms.DateField(
        label="Fecha en que se jugo",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    hora_partido = forms.TimeField(
        label="Hora",
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    imagenes = MultipleFileField(
        label="Imagenes o PDF de la planilla",
        required=True,
        widget=MultipleFileInput(attrs={"multiple": True, "accept": "image/*,application/pdf"}),
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.torneo = kwargs.pop("torneo", None)
        self.partido = None
        super().__init__(*args, **kwargs)

        categorias = Categoria.objects.select_related("torneo").order_by("nombre")
        equipos = Equipo.objects.select_related("categoria").order_by("nombre")

        if self.torneo:
            categorias = categorias.filter(torneo=self.torneo)
            equipos = equipos.filter(categoria__torneo=self.torneo)

        partidos_disponibles = Partido.objects.select_related("categoria", "equipo_local", "equipo_visitante")
        if self.torneo:
            partidos_disponibles = partidos_disponibles.filter(categoria__torneo=self.torneo)

        if self.user and self.user.is_authenticated and not self._usuario_es_editor():
            partidos_disponibles = partidos_disponibles.filter(planilleros=self.user)
            categorias = Categoria.objects.filter(partido__in=partidos_disponibles).distinct().order_by("nombre")
            equipos = equipos.filter(
                Q(partidos_local__planilleros=self.user) | Q(partidos_visitante__planilleros=self.user)
            ).distinct()

        categoria_id = self.data.get("categoria") if self.is_bound else self.initial.get("categoria")
        if categoria_id:
            equipos = equipos.filter(categoria_id=categoria_id)
            partidos_disponibles = partidos_disponibles.filter(categoria_id=categoria_id)

        fechas_fixture = list(
            partidos_disponibles.exclude(numero_fecha__isnull=True)
            .exclude(numero_fecha="")
            .order_by("numero_fecha")
            .values_list("numero_fecha", flat=True)
            .distinct()
        )

        self.fields["categoria"].queryset = categorias
        self.fields["numero_fecha"].choices = [("", "Selecciona la fecha")] + [
            (fecha, fecha) for fecha in fechas_fixture
        ]
        self.fields["equipo_local"].queryset = equipos
        self.fields["equipo_visitante"].queryset = equipos

    def _usuario_es_editor(self):
        if not self.user or not self.user.is_authenticated:
            return False
        if self.user.is_superuser:
            return True
        return (
            AdminTorneo.objects.filter(usuario=self.user, activo=True).exists()
            or AdminOrganizador.objects.filter(usuario=self.user, activo=True).exists()
        )

    def clean(self):
        cleaned = super().clean()
        categoria = cleaned.get("categoria")
        equipo_local = cleaned.get("equipo_local")
        equipo_visitante = cleaned.get("equipo_visitante")

        if equipo_local and equipo_visitante and equipo_local == equipo_visitante:
            raise forms.ValidationError("Equipo A y Equipo B deben ser diferentes.")

        if categoria and equipo_local and equipo_local.categoria_id != categoria.id:
            self.add_error("equipo_local", "Este equipo no pertenece a la categoria seleccionada.")
        if categoria and equipo_visitante and equipo_visitante.categoria_id != categoria.id:
            self.add_error("equipo_visitante", "Este equipo no pertenece a la categoria seleccionada.")

        if categoria and equipo_local and equipo_visitante:
            partidos = Partido.objects.filter(
                categoria=categoria,
                equipo_local=equipo_local,
                equipo_visitante=equipo_visitante,
            )
            if cleaned.get("numero_fecha"):
                partidos = partidos.filter(numero_fecha=cleaned["numero_fecha"])
            partido = partidos.order_by("-fecha", "-hora", "-id").first()
            self.partido = partido

            if self.user and self.user.is_authenticated and not self._usuario_es_editor():
                if not partido or not partido.planilleros.filter(id=self.user.id).exists():
                    raise forms.ValidationError("Solo puedes cargar planillas de partidos asignados a tu usuario.")

        if not cleaned.get("imagenes"):
            self.add_error("imagenes", "Carga al menos una imagen o PDF de la planilla.")

        return cleaned


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = [
            "nombre",
            "descripcion",
            "edad_minima",
            "edad_maxima",
            "controlar_foraneos",
            "porcentaje_minimo_foraneos",
        ]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 3}),
        }


class EquipoForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = [
            "nombre",
            "categoria",
            "responsable",
            "acceso_delegado_hasta",
            "delegado",
            "telefono",
            "director_tecnico",
            "telefono_dt",
            "asistente_tecnico",
            "telefono_at",
            "escudo",
            "activo",
        ]
        widgets = {
            "acceso_delegado_hasta": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local"},
            ),
        }

    def __init__(self, *args, **kwargs):
        torneo = kwargs.pop("torneo", None)
        super().__init__(*args, **kwargs)
        self.fields["acceso_delegado_hasta"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        self.fields["acceso_delegado_hasta"].help_text = "El delegado solo podra editar este equipo hasta esta fecha y hora."
        categorias = Categoria.objects.order_by("nombre")
        if torneo:
            categorias = categorias.filter(torneo=torneo)
        self.fields["categoria"].queryset = categorias
        self.fields["categoria"].label_from_instance = lambda obj: obj.nombre


class EquipoDelegadoForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = [
            "delegado",
            "telefono",
            "director_tecnico",
            "telefono_dt",
            "asistente_tecnico",
            "telefono_at",
            "escudo",
        ]


class EquipoReinscripcionForm(forms.Form):
    categoria_destino = forms.ModelChoiceField(
        queryset=Categoria.objects.none(),
        label="Nueva categoria/torneo",
        empty_label="Selecciona la categoria destino",
    )
    conservar_delegado = forms.BooleanField(
        required=False,
        initial=True,
        label="Conservar usuario delegado responsable",
    )
    conservar_acceso_delegado = forms.BooleanField(
        required=False,
        initial=False,
        label="Copiar fecha de vencimiento del delegado",
    )
    copiar_jugadores_retirados = forms.BooleanField(
        required=False,
        initial=False,
        label="Incluir jugadores retirados",
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        equipo_origen = kwargs.pop("equipo_origen", None)
        super().__init__(*args, **kwargs)
        self.equipo_origen = equipo_origen
        categorias = Categoria.objects.select_related("torneo").order_by("-torneo__fecha_inicio", "torneo__nombre", "nombre")
        if user and not user.is_superuser:
            filtro = Q(torneo__admins_asignados__usuario=user, torneo__admins_asignados__activo=True)
            filtro |= Q(torneo__organizador__admins_asignados__usuario=user, torneo__organizador__admins_asignados__activo=True)
            categorias = categorias.filter(filtro).distinct()
        if equipo_origen and equipo_origen.categoria_id:
            categorias = categorias.exclude(id=equipo_origen.categoria_id)
        self.fields["categoria_destino"].queryset = categorias
        self.fields["categoria_destino"].label_from_instance = lambda obj: f"{obj.torneo.nombre} - {obj.nombre}"

    def clean_categoria_destino(self):
        categoria = self.cleaned_data["categoria_destino"]
        equipo_origen = getattr(self, "equipo_origen", None)
        if equipo_origen and Equipo.objects.filter(categoria=categoria, nombre__iexact=equipo_origen.nombre).exists():
            raise forms.ValidationError("Ya existe un equipo con ese nombre en la categoria destino.")
        return categoria


class JugadorForm(forms.ModelForm):
    class Meta:
        model = Jugador
        fields = [
            "equipo",
            "dorsal",
            "nombres",
            "cedula",
            "fecha_nacimiento",
            "telefono",
            "estado",
            "foto",
            "es_foraneo",
        ]
        widgets = {
            "fecha_nacimiento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        torneo = kwargs.pop("torneo", None)
        super().__init__(*args, **kwargs)
        self.fields["fecha_nacimiento"].input_formats = ["%Y-%m-%d"]
        equipos = Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre")
        if torneo:
            equipos = equipos.filter(categoria__torneo=torneo)
        self.fields["equipo"].queryset = equipos
        self.fields["equipo"].label_from_instance = lambda obj: f"{obj.categoria.nombre} - {obj.nombre}"


class JugadorDelegadoForm(forms.ModelForm):
    class Meta:
        model = Jugador
        fields = [
            "dorsal",
            "nombres",
            "cedula",
            "fecha_nacimiento",
            "telefono",
            "estado",
            "foto",
            "es_foraneo",
        ]
        widgets = {
            "fecha_nacimiento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_nacimiento"].input_formats = ["%Y-%m-%d"]


class PartidoForm(forms.ModelForm):
    class Meta:
        model = Partido
        fields = [
            "categoria",
            "equipo_local",
            "equipo_visitante",
            "planilleros",
            "fecha",
            "hora",
            "estado",
            "estadisticas_validadas",
            "numero_fecha",
            "grupo",
            "cancha",
            "estado_programacion",
            "fase",
            "goles_local",
            "goles_visitante",
            "ajuste_puntos_local",
            "ajuste_puntos_visitante",
            "observacion_comite",
            "goles_local_penales",
            "goles_visitante_penales",
        ]
        widgets = {
            "fecha": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "hora": forms.TimeInput(attrs={"type": "time"}),
            "observacion_comite": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        torneo = kwargs.pop("torneo", None)
        super().__init__(*args, **kwargs)
        categorias = Categoria.objects.order_by("nombre")
        equipos = Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre")
        if torneo:
            categorias = categorias.filter(torneo=torneo)
            equipos = equipos.filter(categoria__torneo=torneo)
        self.fields["categoria"].queryset = categorias
        self.fields["categoria"].label_from_instance = lambda obj: obj.nombre
        self.fields["equipo_local"].queryset = equipos
        self.fields["equipo_visitante"].queryset = equipos
        self.fields["equipo_local"].label_from_instance = lambda obj: f"{obj.categoria.nombre} - {obj.nombre}"
        self.fields["equipo_visitante"].label_from_instance = lambda obj: f"{obj.categoria.nombre} - {obj.nombre}"
        self.fields["fecha"].input_formats = ["%Y-%m-%d"]
        planilleros_asignados = []
        if self.instance and self.instance.pk:
            planilleros_asignados = list(self.instance.planilleros.values_list("id", flat=True))
        if planilleros_asignados:
            self.fields["planilleros"].queryset = User.objects.filter(
                id__in=planilleros_asignados,
                is_active=True,
            ).order_by("username")
        else:
            self.fields["planilleros"].queryset = User.objects.filter(
                is_staff=False,
                is_active=True,
            ).order_by("username")
        self.fields["planilleros"].help_text = "Si el partido ya tiene planilleros asignados, solo aparecen esos usuarios."

    def clean(self):
        cleaned_data = super().clean()
        categoria = cleaned_data.get("categoria")
        equipo_local = cleaned_data.get("equipo_local")
        equipo_visitante = cleaned_data.get("equipo_visitante")

        if categoria and equipo_local and equipo_local.categoria_id != categoria.id:
            self.add_error("equipo_local", "El equipo local no pertenece a la categoría seleccionada.")

        if categoria and equipo_visitante and equipo_visitante.categoria_id != categoria.id:
            self.add_error("equipo_visitante", "El equipo visitante no pertenece a la categoría seleccionada.")

        if equipo_local and equipo_visitante and equipo_local.id == equipo_visitante.id:
            self.add_error("equipo_visitante", "El visitante debe ser diferente al local.")

        return cleaned_data


class PartidoProgramacionForm(PartidoForm):
    class Meta(PartidoForm.Meta):
        fields = [
            "categoria",
            "equipo_local",
            "equipo_visitante",
            "planilleros",
            "fecha",
            "hora",
            "estado",
            "numero_fecha",
            "grupo",
            "cancha",
            "estado_programacion",
            "fase",
        ]
