// Shared API types. Money is always a decimal STRING over the wire (never a
// JSON number), matching the backend contract to avoid float rounding.

export type PaymentMethod = "efectivo" | "tarjeta";

export interface Product {
  sku: string;
  name: string;
  /** Decimal string, e.g. "1500.00". */
  price: string;
  stock: number;
}

export interface ProductCreate {
  sku: string;
  name: string;
  /** Decimal string. */
  price: string;
  stock: number;
}

export interface ProductUpdate {
  name?: string;
  /** Decimal string. */
  price?: string;
  stock?: number;
}

export interface SaleItemRequest {
  sku: string;
  qty: number;
}

export interface SaleItemResponse {
  sku: string;
  qty: number;
  /** Decimal string. */
  unit_price: string;
  /** Decimal string. */
  subtotal: string;
}

export interface SaleCreate {
  items: SaleItemRequest[];
  payment_method: PaymentMethod;
}

export interface Sale {
  sale_id: string;
  /** Decimal string. */
  total: string;
  payment_method: PaymentMethod;
  /** ISO-8601 timestamp. */
  timestamp: string;
  items: SaleItemResponse[];
}

export interface DailyReport {
  date: string;
  sales_count: number;
  /** Decimal string. */
  total: string;
  /** Map of payment method -> decimal string total. */
  by_payment_method: Record<string, string>;
}

// --- SmartPOS Copilot -----------------------------------------------------

export interface PromoCombo {
  nombre: string;
  skus: string[];
  /** Decimal string. */
  precio_original: string;
  /** Decimal string. */
  precio_combo: string;
  /** Decimal string. */
  ahorro: string;
  pitch_cajero: string;
}

export interface ResumenGerencial {
  fecha: string;
  /** Decimal string. */
  total_ventas: string;
  productos_criticos: string[];
  recomendacion_estrategica: string;
}

// --- Error envelope -------------------------------------------------------

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}
