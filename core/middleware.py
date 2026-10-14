"""El servicio local rechaza conexiones que no vienen de loopback."""

import ipaddress

from django.http import HttpResponseForbidden


class LoopbackMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            local = ipaddress.ip_address(request.META.get("REMOTE_ADDR", "")).is_loopback
        except ValueError:
            local = False
        if not local:
            return HttpResponseForbidden("Esta herramienta solo permite acceso local.")
        return self.get_response(request)
