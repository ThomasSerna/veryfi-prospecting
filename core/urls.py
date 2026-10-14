"""Rutas de la interfaz; conserva sus nombres públicos y el namespace existente."""

from django.urls import path

from core import views

app_name = "webapp"

urlpatterns = [
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
