"""Sugerencias iniciales del asistente — "¿con qué te puedo ayudar?".

Lista curada de preguntas frecuentes agrupadas por tema. Se muestran como botones
clicables al entrar al asistente (antes de escribir nada). Cada pregunta está redactada
para que caiga bien en el manual (docs/manual/*). Mantener en sincronía con el manual.
"""
from __future__ import annotations

SUGGESTION_GROUPS: list[dict[str, object]] = [
    {
        "topic": "Primeros pasos",
        "icon": "rocket_launch",
        "questions": [
            "Cómo va el día hoy",
            "Cómo creo una empresa",
            "Cómo doy de alta un usuario y le doy permisos",
            "Qué puede hacer el sistema",
        ],
    },
    {
        "topic": "Caja y ventas",
        "icon": "point_of_sale",
        "questions": [
            "Cuánto vendí hoy",
            "Cómo va el corte de caja de hoy",
            "Hay alguna caja abierta",
            "Cómo hago una venta en caja",
        ],
    },
    {
        "topic": "Inventario",
        "icon": "inventory_2",
        "questions": [
            "Qué productos están por agotarse",
            "Cuánto vale el inventario",
            "Cómo registro un producto",
            "Cómo hago un conteo físico",
        ],
    },
    {
        "topic": "Compras",
        "icon": "shopping_cart",
        "questions": [
            "Cómo hago una orden de compra",
            "Cómo recibo la mercadería",
            "Cómo registro un proveedor",
        ],
    },
    {
        "topic": "Recursos Humanos",
        "icon": "badge",
        "questions": [
            "Cuántos empleados hay",
            "Cuántos empleados cotizan INSS",
            "Cómo registro un empleado",
            "Cómo le pongo un complemento de salario",
        ],
    },
    {
        "topic": "Nómina",
        "icon": "payments",
        "questions": [
            "Cómo armo una planilla",
            "Cómo configuro las tasas de nómina",
            "Cómo calcula el sistema el INSS y el IR",
        ],
    },
    {
        "topic": "Cartera y terceros",
        "icon": "account_balance_wallet",
        "questions": [
            "Cuánto me deben los clientes",
            "Cuánto debo a proveedores",
            "Cuántos clientes hay",
            "Cuántos proveedores hay",
        ],
    },
    {
        "topic": "Tesorería y libros",
        "icon": "account_balance",
        "questions": [
            "Cómo va el arqueo de caja de hoy",
            "Hay extractos bancarios sin conciliar",
            "Cuál es el período fiscal abierto",
            "Cuál es el último tipo de cambio",
            "Hay cruces entre empresas pendientes",
        ],
    },
    {
        "topic": "Café (financiamiento y beneficio)",
        "icon": "coffee",
        "questions": [
            "Cuántos préstamos activos hay",
            "Cuánto café hay en custodia",
            "Cuántas solicitudes de crédito hay por aprobar",
            "Cuántas órdenes de beneficio hay en proceso",
        ],
    },
    {
        "topic": "Campo y flota",
        "icon": "agriculture",
        "questions": [
            "Cuántas órdenes de trabajo hay",
            "Cuántos lotes activos hay",
            "Qué activos necesitan mantenimiento",
            "Cuánto combustible consumió la flota este mes",
        ],
    },
    {
        "topic": "Supervisión",
        "icon": "shield",
        "questions": [
            "Qué necesita atención hoy",
            "Detállame la bitácora",
            "Hay alertas críticas",
            "El sistema detectó errores",
        ],
    },
]
