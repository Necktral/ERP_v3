from drf_spectacular.generators import SchemaGenerator


def test_openapi_schema_generation_covers_procurement_order_actions():
    schema = SchemaGenerator().get_schema(request=None, public=True)

    assert schema is not None
    assert "/api/procurement/orders/{order_id}/approve/" in schema["paths"]
    assert "post" in schema["paths"]["/api/procurement/orders/{order_id}/approve/"]
    assert "jwtAuthWithOrgContext" in schema["components"]["securitySchemes"]
