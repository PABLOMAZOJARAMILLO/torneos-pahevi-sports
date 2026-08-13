from django import forms

from torneos.models import Categoria

from .models import AbonoInscripcion, Egreso


class AbonoForm(forms.ModelForm):
    forma_pago = forms.ChoiceField(choices=[(x, x) for x in ["Efectivo", "Transferencia", "Nequi", "Daviplata", "Otro"]])

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
    class Meta:
        model = Egreso
        fields = ["categoria", "concepto", "valor", "fecha", "forma_pago", "soporte", "observacion"]
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"}), "soporte": forms.ClearableFileInput(attrs={"accept": "image/*", "capture": "environment"}), "observacion": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, torneo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].required = False
        self.fields["categoria"].empty_label = "Fondo general"
        self.fields["categoria"].queryset = Categoria.objects.filter(torneo=torneo).order_by("nombre")

    def clean_valor(self):
        valor = self.cleaned_data["valor"]
        if valor <= 0:
            raise forms.ValidationError("El valor debe ser mayor que cero.")
        return valor
