from django.urls import path

from . import views

app_name = "contabilidad"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("seleccionar-torneo/", views.seleccionar_torneo, name="seleccionar_torneo"),
    path("configurar/", views.configurar, name="configurar"),
    path("cuentas/<int:cuenta_id>/", views.cuenta, name="cuenta"),
    path("abonos/<int:abono_id>/editar/", views.editar_abono, name="editar_abono"),
    path("cuentas/<int:cuenta_id>/pagar-tarjetas/", views.pagar_tarjetas, name="pagar_tarjetas"),
    path("egresos/nuevo/", views.nuevo_egreso, name="nuevo_egreso"),
    path("ingresos/nuevo/", views.nuevo_ingreso, name="nuevo_ingreso"),
    path("movimientos/<str:tipo>/<int:movimiento_id>/anular/", views.anular_movimiento, name="anular_movimiento"),
    path("tarjetas/", views.tarjetas, name="tarjetas"),
    path("tarjetas/reporte/", views.reporte_tarjetas, name="reporte_tarjetas"),
    path("reporte/", views.reporte, name="reporte"),
]
