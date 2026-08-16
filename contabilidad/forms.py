from django import forms

from torneos.models import Categoria, Partido

from .models import AbonoInscripcion, Egreso, Ingreso


FORMAS_PAGO = [(x, x) for x in ["Efectivo", "Transferencia", "Nequi", "Daviplata", "Otro"]]
CONCEPTOS_INGRESO = [(x, x) for x in ["Pago de arbitraje", "Patrocinio", "Venta de alimentos", "Venta de entradas", "Multas", "Otro ingreso"]]
CONCEPTOS_EGRESO = [(x, x) for x in ["Pago de árbitros", "Premiación", "Alquiler de cancha", "Implementos deportivos", "Publicidad", "Refrigerios", "Transporte", "Otro egreso"]]


class AbonoForm(forms.ModelForm):
    forma_pago = forms.ChoiceField(choices=FORMAS_PAGO)

    class Meta:
        model = AbonoInscripcion
        fields = ["valor", "fecha", "observacion"]
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"})}

    def clean_valor(self):
        valor = self.cleaned_data["valor"]
        if valor <= 0:
            raise forms.ValidationError("El valor debe ser mayor que cero.")
        return valor


class EgresoForm(forms.ModelForm):
    concepto = forms.ChoiceField(choices=CONCEPTOS_EGRESO)
    forma_pago = forms.ChoiceField(choices=FORMAS_PAGO)
    class Meta:
        model = Egreso
        fields = ["categoria", "concepto", "partidos", "valor", "fecha", "forma_pago", "soporte", "observacion"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "partidos": forms.CheckboxSelectMultiple(),
            "soporte": forms.ClearableFileInput(attrs={"accept": "image/*", "capture": "environment"}),
            "observacion": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, torneo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].required = False
        self.fields["categoria"].empty_label = "Fondo general"
        self.fields["categoria"].queryset = Categoria.objects.filter(torneo=torneo).order_by("nombre")
        self.fields["categoria"].label = "Fondo que paga el egreso"
        self.fields["categoria"].help_text = "Selecciona el fondo de inscripción de una categoría o el fondo general del torneo."
        self.fields["partidos"].required = False
        self.fields["partidos"].label = "Partidos en los que se pagó arbitraje (opcional)"
        self.fields["partidos"].help_text = "Puedes marcar uno o varios partidos incluidos en este pago."
        self.fields["partidos"].queryset = Partido.objects.filter(
            categoria__torneo=torneo,
        ).select_related("categoria", "equipo_local", "equipo_visitante").order_by(
            "-fecha", "-hora", "categoria__nombre",
        )
        self.fields["partidos"].label_from_instance = lambda partido: (
            f"{partido.fecha:%d/%m/%Y} · {partido.categoria.nombre} · "
            f"{partido.equipo_local.nombre} vs {partido.equipo_visitante.nombre}"
        )

    def clean(self):
        datos = super().clean()
        if datos.get("concepto") != "Pago de árbitros":
            datos["partidos"] = Partido.objects.none()
        return datos

    def clean_valor(self):
        valor = self.cleaned_data["valor"]
        if valor <= 0:
            raise forms.ValidationError("El valor debe ser mayor que cero.")
        return valor


class IngresoManualForm(forms.ModelForm):
    concepto = forms.ChoiceField(choices=CONCEPTOS_INGRESO)
    forma_pago = forms.ChoiceField(choices=FORMAS_PAGO)

    class Meta:
        model = Ingreso
        fields = ["categoria", "concepto", "partidos", "valor", "fecha", "forma_pago", "detalle"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "partidos": forms.CheckboxSelectMultiple(),
            "detalle": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, torneo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].required = False
        self.fields["categoria"].empty_label = "Fondo general"
        self.fields["categoria"].queryset = Categoria.objects.filter(torneo=torneo).order_by("nombre")
        self.fields["detalle"].label = "Descripción"
        self.fields["partidos"].required = False
        self.fields["partidos"].label = "Partidos que generan el ingreso de arbitraje (opcional)"
        self.fields["partidos"].help_text = "Puedes marcar uno o varios partidos incluidos en este recaudo."
        self.fields["partidos"].queryset = Partido.objects.filter(
            categoria__torneo=torneo,
        ).select_related("categoria", "equipo_local", "equipo_visitante").order_by(
            "-fecha", "-hora", "categoria__nombre",
        )
        self.fields["partidos"].label_from_instance = lambda partido: (
            f"{partido.fecha:%d/%m/%Y} · {partido.categoria.nombre} · "
            f"{partido.equipo_local.nombre} vs {partido.equipo_visitante.nombre}"
        )

    def clean(self):
        datos = super().clean()
        if datos.get("concepto") != "Pago de arbitraje":
            datos["partidos"] = Partido.objects.none()
        return datos

    def clean_valor(self):
        valor = self.cleaned_data["valor"]
        if valor <= 0:
            raise forms.ValidationError("El valor debe ser mayor que cero.")
        return valor
