/**
 * Diccionario central de códigos del backend → mensaje en español claro.
 *
 * El backend responde códigos crudos (SALES_*, PAYMENTS_*, PORTFOLIO_*,
 * INVENTORY_COUNT_*, BILLING_*, SYNC_*) en el `detail` del envelope de error;
 * `apiErrorMessage` (src/core/api) consulta este diccionario antes de mostrar
 * el mensaje al usuario del campo. Cubre los códigos que un usuario puede ver
 * por la UI; los internos de management commands quedan fuera a propósito.
 *
 * Para códigos sin traducción se devuelve el código tal cual (fallback
 * honesto: mejor un código crudo que un mensaje inventado).
 */

/** Formato de código del backend: MAYÚSCULAS con guiones bajos. */
const RE_CODIGO = /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$/;

export const CODIGOS: Readonly<Record<string, string>> = {
  // --- Ventas / POS (SalesError en modulos/ventas/services.py) ---
  SALES_AMOUNT_EXCEEDS_OUTSTANDING: 'El abono excede el saldo pendiente de la cuenta.',
  SALES_AMOUNT_INVALID: 'Monto inválido: debe ser mayor que cero.',
  SALES_CREDIT_MUST_BE_ONLY_PAYMENT: 'El crédito debe ser la única forma de pago de la venta.',
  SALES_CREDIT_REQUIRES_CUSTOMER: 'La venta al crédito requiere un cliente identificado.',
  SALES_IDEMPOTENCY_REQUIRED: 'Falta la clave de idempotencia de la operación; reintentá desde el POS.',
  SALES_INSUFFICIENT_STOCK: 'Stock insuficiente para completar la venta.',
  SALES_INVALID_PAYMENT_METHOD: 'Método de pago inválido.',
  SALES_ITEM_NOT_FOUND: 'El artículo no existe en el catálogo de esta sucursal.',
  SALES_ITEM_WITHOUT_PRICE: 'El artículo no tiene precio de venta configurado.',
  SALES_LINES_REQUIRED: 'La venta requiere al menos una línea.',
  SALES_NO_CREDIT_ACCOUNT: 'El cliente no tiene cuenta de crédito activa.',
  SALES_NO_OPEN_CASH_SESSION: 'No hay sesión de caja abierta en esta sucursal.',
  SALES_OVERRIDE_BAD_CREDENTIALS: 'Credenciales del supervisor incorrectas.',
  SALES_OVERRIDE_EXPIRED: 'La autorización del supervisor expiró; pedila de nuevo.',
  SALES_OVERRIDE_INVALID: 'Autorización de supervisor inválida o ya usada.',
  SALES_OVERRIDE_NOT_AUTHORIZED: 'Ese usuario no puede autorizar esta operación.',
  SALES_OVERRIDE_REASON_REQUIRED: 'La autorización del supervisor requiere un motivo.',
  SALES_OVERRIDE_SELF: 'Nadie puede autorizarse a sí mismo; requiere otro supervisor.',
  SALES_PAYMENTS_MISMATCH: 'Los pagos no cuadran con el total de la venta.',
  SALES_PAYMENTS_REQUIRED: 'La venta requiere al menos una forma de pago.',
  SALES_PRICE_OVERRIDE_FORBIDDEN: 'Cambiar el precio o aplicar descuento requiere autorización de supervisor.',
  SALES_RECEIVABLE_NOT_FOUND: 'La cuenta por cobrar no existe.',
  SALES_RECEIVABLE_NOT_OPEN: 'La cuenta por cobrar ya no está abierta (saldada o anulada).',
  SALES_SELF_SERVICE_CODE_EXHAUSTED: 'No se pudo generar un código de autoservicio; intentá de nuevo.',
  SALES_SELF_SERVICE_EXPIRED: 'El pedido de autoservicio expiró.',
  SALES_SELF_SERVICE_NOT_FOUND: 'El código de autoservicio no existe.',
  SALES_SELF_SERVICE_NOT_OPEN: 'El pedido de autoservicio ya no está abierto.',

  // --- Pagos / conciliación bancaria (PaymentsDomainError en kernels/payments) ---
  PAYMENTS_BANK_ACCOUNT_DUPLICATE: 'Ya existe una cuenta bancaria con esos datos.',
  PAYMENTS_BANK_ACCOUNT_INVALID: 'Datos de la cuenta bancaria inválidos.',
  PAYMENTS_BANK_ACCOUNT_NOT_FOUND: 'La cuenta bancaria no existe.',
  PAYMENTS_EXCLUDE_REASON_REQUIRED: 'Excluir una línea del estado de cuenta requiere un motivo.',
  PAYMENTS_INTENT_ALREADY_MATCHED: 'Ese pago ya fue conciliado con otra línea.',
  PAYMENTS_INTENT_NOT_FOUND: 'El intento de pago no existe.',
  PAYMENTS_MATCH_AMOUNT_MISMATCH: 'El monto de la línea no coincide con el del pago.',
  PAYMENTS_MATCH_CURRENCY_MISMATCH: 'La moneda de la línea no coincide con la del pago.',
  PAYMENTS_MATCH_METHOD_NOT_BANKABLE: 'Ese método de pago no se concilia contra banco (p. ej. efectivo).',
  PAYMENTS_MATCH_SIGN_MISMATCH: 'El signo del movimiento bancario no corresponde con el pago.',
  PAYMENTS_STATEMENT_LINE_ALREADY_MATCHED: 'La línea del estado de cuenta ya fue conciliada.',
  PAYMENTS_STATEMENT_LINE_AMOUNT_INVALID: 'Una línea del estado de cuenta tiene monto inválido.',
  PAYMENTS_STATEMENT_LINE_NOT_FOUND: 'La línea del estado de cuenta no existe.',
  PAYMENTS_STATEMENT_LINES_PENDING: 'Aún hay líneas sin conciliar ni excluir; no se puede cerrar el estado.',
  PAYMENTS_STATEMENT_LINES_REQUIRED: 'El estado de cuenta requiere al menos una línea.',
  PAYMENTS_STATEMENT_NOT_FOUND: 'El estado de cuenta no existe.',
  PAYMENTS_STATEMENT_NOT_OPEN: 'El estado de cuenta ya no está abierto.',
  PAYMENTS_STATEMENT_PERIOD_INVALID: 'Período del estado de cuenta inválido.',
  PAYMENTS_STATEMENT_UNBALANCED: 'El estado de cuenta no cuadra: los saldos no coinciden con las líneas.',

  // --- Cartera (PortfolioDomainError en kernels/portfolio; llega como {error, message}) ---
  ALREADY_WRITTEN_OFF: 'La cuenta ya fue saneada; no admite más operaciones.',
  AUTO_ALLOCATION_DISABLED: 'La asignación automática de pagos está deshabilitada para esta empresa.',
  CANNOT_WRITEOFF_PAID: 'No se puede sanear una cuenta que ya está pagada.',
  CURRENCY_MISMATCH: 'Las monedas de la operación no coinciden.',
  EXCEEDS_APPROVED: 'El desembolso excede el monto aprobado del crédito.',
  EXCEEDS_OUTSTANDING: 'El monto excede el saldo pendiente.',
  EXCEEDS_PAYMENT: 'La asignación excede el monto del pago.',
  INVALID_ADJUSTMENT: 'Ajuste inválido: dejaría la cuenta con saldo negativo.',
  INVALID_AMOUNT: 'Monto inválido: debe ser mayor que cero.',
  INVALID_DATE: 'Fecha inválida (use el formato YYYY-MM-DD).',
  INVALID_PARTIES: 'Terceros inválidos para esta operación (p. ej. acreedor y deudor iguales).',
  INVALID_RATE: 'La tasa de interés no puede ser negativa.',
  INVALID_STATUS: 'El estado actual del registro no permite esta operación.',
  OBLIGATION_NOT_OPEN: 'La obligación no está abierta; no admite abonos.',
  PAYMENT_NOT_CAPTURED: 'El pago aún no está capturado; no se puede asignar.',
  PORTFOLIO_INVALID_REMINDER_LEVEL: 'Nivel de recordatorio fuera de rango (1-3).',
  PORTFOLIO_NO_OVERDUE_RECEIVABLES: 'El cliente no tiene cuentas vencidas.',

  // --- Conteo físico de inventario (InventoryCountError en kernels/inventarios/counting.py) ---
  INVENTORY_COUNT_LINE_NOT_FOUND: 'La línea del conteo no existe.',
  INVENTORY_COUNT_LINES_REQUIRED: 'Registrá al menos una línea contada.',
  INVENTORY_COUNT_NO_ITEMS: 'No hay artículos con kardex en esa bodega para contar.',
  INVENTORY_COUNT_NOT_COUNTED: 'El conteo aún no tiene cantidades registradas; no se puede aprobar.',
  INVENTORY_COUNT_NOT_FOUND: 'El conteo físico no existe.',
  INVENTORY_COUNT_NOT_OPEN: 'El conteo ya no está abierto.',
  INVENTORY_COUNT_QTY_INVALID: 'Cantidad contada inválida: debe ser cero o mayor.',
  INVENTORY_COUNT_SOD_SELF_APPROVAL: 'Quien registró el conteo no puede aprobarlo (segregación de funciones).',
  INVENTORY_COUNT_WAREHOUSE_NOT_FOUND: 'La bodega indicada no existe.',

  // --- Facturación vía riel offline (SyncRejectError en sync_engine/handlers_billing.py) ---
  BILLING_INVALID_SCOPE: 'La empresa o sucursal del comando no es válida.',
  BILLING_INVENTORY_ERROR: 'Error de inventario al facturar (artículo o stock).',
  BILLING_NOT_FOUND: 'Documento de facturación no encontrado.',
  BILLING_SCHEMA_INVALID: 'Datos de facturación incompletos o inválidos.',

  // --- Riel de sincronización offline (reason codes en sync_engine/services.py) ---
  SYNC_BATCH_RECEIVED: 'Lote de sincronización recibido.',
  SYNC_COMMAND_APPLIED: 'Comando aplicado correctamente.',
  SYNC_COMMAND_DUPLICATE: 'Comando duplicado: ya se había aplicado antes.',
  SYNC_COMMAND_REJECTED: 'Comando rechazado por el servidor.',
  SYNC_DEVICE_QUARANTINED: 'El dispositivo está en cuarentena; contactá al administrador.',
  SYNC_DEVICE_REVOKED: 'El dispositivo fue revocado; no puede sincronizar.',
  SYNC_DUPLICATE: 'Comando duplicado: ya se había aplicado antes.',
  SYNC_FORBIDDEN_SCOPE: 'El dispositivo no tiene permiso sobre esa empresa o sucursal.',
  SYNC_INTERNAL_ERROR: 'Error interno al aplicar el comando de sincronización.',
  SYNC_INVALID_SIGNATURE: 'Firma del lote inválida; el dispositivo debe re-enrolarse.',
  SYNC_LIMIT_EXCEEDED: 'El lote de sincronización excede los límites permitidos.',
  SYNC_OK: 'Sincronización correcta.',
  SYNC_PAYLOAD_MISMATCH: 'Reintento con datos distintos al comando original.',
  SYNC_SCHEMA_INVALID: 'El comando de sincronización tiene formato inválido.',
  SYNC_TIME_SKEW: 'El reloj del dispositivo está desfasado; ajustá la hora e intentá de nuevo.',
};

/** true si el texto tiene formato de código del backend (CODIGO_EN_MAYUSCULAS). */
export function esCodigoBackend(valor: string): boolean {
  return RE_CODIGO.test(valor.trim());
}

/**
 * Traduce un código del backend a español claro. Para códigos sin traducción
 * devuelve el código tal cual (fallback honesto).
 */
export function traducirCodigo(codigo: string): string {
  return CODIGOS[codigo.trim()] ?? codigo;
}
