from drf_spectacular.extensions import OpenApiAuthenticationExtension


class JWTAuthWithOrgContextScheme(OpenApiAuthenticationExtension):
    target_class = "apps.modulos.iam.authentication.JWTAuthWithOrgContext"
    name = "jwtAuthWithOrgContext"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "JWT de acceso. Los endpoints operativos requieren además "
                "X-Company-Id y, para membresías limitadas, X-Branch-Id."
            ),
        }
