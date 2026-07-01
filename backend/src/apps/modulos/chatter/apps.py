from django.apps import AppConfig


class ChatterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modulos.chatter"
    label = "chatter"
    verbose_name = "Notas por registro (chatter)"
