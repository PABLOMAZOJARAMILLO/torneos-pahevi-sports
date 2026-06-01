from django import forms

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


class AdminTorneoForm(forms.ModelForm):
    class Meta:
        model = AdminTorneo
        fields = [
            "usuario",
            "puede_editar",
            "puede_validar",
            "puede_programar",
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
            "activo",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = self.fields["usuario"].queryset.filter(is_staff=True).order_by("username")
        self.fields["usuario"].label_from_instance = lambda obj: obj.get_full_name() or obj.username


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
        if torneo:
            self.fields["torneo"].queryset = Torneo.objects.filter(id=torneo.id)
            self.fields["torneo"].initial = torneo
        if not self.instance.pk:
            self.fields["archivo_subido"].required = True


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
            "fecha": forms.DateInput(attrs={"type": "date"}),
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
