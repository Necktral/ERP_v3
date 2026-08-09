from django.apps import AppConfig


class IamConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modulos.iam"
    label = "iam"

    def ready(self):
        # Registra extensiones de documentación sin importar infraestructura
        # OpenAPI desde el camino de autenticación en runtime.
        from apps.modulos.iam import schema  # noqa: F401
