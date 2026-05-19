from django import forms

from .models import Torneo, Documento, Categoria, Equipo, Jugador, Partido


class TorneoForm(forms.ModelForm):
    class Meta:
        model = Torneo
        fields = [
            "nombre",
            "descripcion",
            "fecha_inicio",
            "fecha_fin",
            "estado",
        ]
        widgets = {
            "fecha_inicio": forms.DateInput(attrs={"type": "date"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date"}),
            "descripcion": forms.Textarea(attrs={"rows": 3}),
        }


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
            "delegado",
            "telefono",
            "director_tecnico",
            "telefono_dt",
            "asistente_tecnico",
            "telefono_at",
            "escudo",
            "activo",
        ]

    def __init__(self, *args, **kwargs):
        torneo = kwargs.pop("torneo", None)
        super().__init__(*args, **kwargs)
        categorias = Categoria.objects.order_by("nombre")
        if torneo:
            categorias = categorias.filter(torneo=torneo)
        self.fields["categoria"].queryset = categorias
        self.fields["categoria"].label_from_instance = lambda obj: obj.nombre


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
        ]
        widgets = {
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        torneo = kwargs.pop("torneo", None)
        super().__init__(*args, **kwargs)
        equipos = Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre")
        if torneo:
            equipos = equipos.filter(categoria__torneo=torneo)
        self.fields["equipo"].queryset = equipos
        self.fields["equipo"].label_from_instance = lambda obj: f"{obj.categoria.nombre} - {obj.nombre}"


class PartidoForm(forms.ModelForm):
    class Meta:
        model = Partido
        fields = [
            "categoria",
            "equipo_local",
            "equipo_visitante",
            "fecha",
            "hora",
            "estado",
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
