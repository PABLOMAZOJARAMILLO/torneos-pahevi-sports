from django import forms

from .models import Documento, Equipo, Jugador, Partido


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = [
            "tipo",
            "titulo",
            "descripcion",
            "archivo",
            "activo",
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
