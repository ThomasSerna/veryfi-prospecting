"""Rutas del servicio local y estáticos sin activar pantallas de depuración."""

from django.contrib.staticfiles.views import serve
from django.urls import include, path, re_path

from webapp import views

app_name = "webapp"

patterns = [
    path("", views.campaigns, name="campaigns"),
    path("campaigns/new/", views.new_campaign, name="new_campaign"),
    path("campaigns/<uuid:campaign_id>/", views.campaign, name="campaign"),
    path("campaigns/<uuid:campaign_id>/status/", views.status, name="status"),
    path("campaigns/<uuid:campaign_id>/execute/", views.execute, name="execute"),
    path("campaigns/<uuid:campaign_id>/finish/", views.close, name="close"),
    path("campaigns/<uuid:campaign_id>/export/", views.export, name="export"),
    path("campaigns/<uuid:campaign_id>/companies/<uuid:company_id>/", views.company, name="company"),
    path("campaigns/<uuid:campaign_id>/companies/<uuid:company_id>/review/", views.review, name="review"),
    path("campaigns/<uuid:campaign_id>/companies/<uuid:company_id>/confirm/", views.confirm_channel, name="confirm_channel"),
]

urlpatterns = [path("", include((patterns, app_name), namespace=app_name)),
               re_path(r"^static/(?P<path>.*)$", serve, {"insecure": True})]
