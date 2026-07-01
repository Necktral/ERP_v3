/** Códigos de negocio de compras → mensaje en español para el usuario. */
export const MENSAJES_COMPRAS: Record<string, string> = {
  PROCUREMENT_SOD_SELF_APPROVAL: 'Quien envía no puede aprobar: debe aprobar otra persona.',
  PROCUREMENT_LINE_COST_REQUIRED:
    'Una línea no tiene costo: poné el costo o registrá el precio del proveedor (pestaña Precios proveedor).',
  PROCUREMENT_LINE_COST_INVALID: 'El costo de una línea no es válido.',
  PROCUREMENT_LINE_QTY_INVALID: 'La cantidad de una línea no es válida.',
  PROCUREMENT_LINES_REQUIRED: 'Hay que agregar al menos una línea.',
  PROCUREMENT_ITEM_NOT_FOUND: 'Un artículo no existe o está inactivo.',
  PROCUREMENT_SUPPLIER_REQUIRED: 'Hay que elegir el proveedor.',
  PROCUREMENT_ORDER_NOT_DRAFT: 'La orden ya no es borrador.',
  PROCUREMENT_ORDER_NOT_PENDING: 'La orden no está pendiente de aprobación.',
  PROCUREMENT_ORDER_NOT_APPROVED: 'La orden no está aprobada.',
  PROCUREMENT_ORDER_NOT_RECEIVABLE: 'La orden no admite recepciones (debe estar enviada).',
  PROCUREMENT_ORDER_NOT_INVOICEABLE: 'La orden no admite facturas en este estado.',
  PROCUREMENT_ORDER_NOT_CLOSABLE: 'La orden no se puede cerrar en este estado.',
  PROCUREMENT_ORDER_NOT_CANCELLABLE: 'La orden no se puede cancelar en este estado.',
  PROCUREMENT_ORDER_HAS_RECEIPTS:
    'La orden ya tiene mercadería recibida: no se cancela, se cierra (acepta lo pendiente como no entregado).',
  PROCUREMENT_OVER_RECEIPT: 'Se intentó recibir más de lo pendiente en una línea.',
  PROCUREMENT_IDEMPOTENCY_REQUIRED: 'Falta la clave de idempotencia (reintentá desde la pantalla).',
  PROCUREMENT_MATCH_OUT_OF_TOLERANCE:
    'La factura no cuadra con lo recibido (fuera de tolerancia). Revisá montos o forzá con autorización.',
  PROCUREMENT_MATCH_NOTHING_TO_INVOICE:
    'No hay valor recibido pendiente de facturar (puede haber un borrador de factura previo que ya lo consume).',
  PROCUREMENT_MATCH_OVERRIDE_FORBIDDEN: 'No tenés permiso para forzar el match fuera de tolerancia.',
  PROCUREMENT_REQ_NOT_DRAFT: 'La requisición ya no es borrador.',
  PROCUREMENT_REQ_NOT_SUBMITTED: 'La requisición no está enviada.',
  PROCUREMENT_REQ_NOT_APPROVED: 'La requisición no está aprobada.',
  PROCUREMENT_REASON_REQUIRED: 'Hay que escribir el motivo.',
};

/** Ola D: pago de CxP desde caja. */
export const MENSAJES_PAGO_CXP: Record<string, string> = {
  PROCUREMENT_PAYABLE_NOT_FOUND: 'La cuenta por pagar no existe en esta empresa.',
  PROCUREMENT_PAYABLE_NOT_OPEN: 'Esa cuenta por pagar ya está saldada o cerrada.',
  PROCUREMENT_AMOUNT_EXCEEDS_OUTSTANDING: 'El monto supera el saldo pendiente con el proveedor.',
  PROCUREMENT_AMOUNT_INVALID: 'El monto del pago no es válido.',
  PROCUREMENT_INVALID_PAYMENT_METHOD: 'Método de pago no permitido para pagar proveedores.',
  PROCUREMENT_CASH_SESSION_REQUIRED:
    'Para pagar en efectivo hay que tener una sesión de caja abierta.',
};
