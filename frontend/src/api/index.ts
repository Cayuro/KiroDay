// Endpoint functions grouped by domain. Each returns typed data and throws
// ApiError on failure (decoded from the backend error envelope).

import { request } from "./client";
import type {
  DailyReport,
  Product,
  ProductCreate,
  ProductUpdate,
  PromoCombo,
  ResumenGerencial,
  Sale,
  SaleCreate,
} from "./types";

export { ApiError, getBaseUrl } from "./client";
export * from "./types";

// --- Catalog --------------------------------------------------------------

export function listProducts(): Promise<Product[]> {
  return request<Product[]>("/products");
}

export function createProduct(product: ProductCreate): Promise<Product> {
  return request<Product>("/products", { method: "POST", body: product });
}

export function updateProduct(sku: string, changes: ProductUpdate): Promise<Product> {
  return request<Product>(`/products/${encodeURIComponent(sku)}`, {
    method: "PUT",
    body: changes,
  });
}

// --- Sales ----------------------------------------------------------------

export function registerSale(sale: SaleCreate): Promise<Sale> {
  return request<Sale>("/sales", { method: "POST", body: sale });
}

// --- Reports --------------------------------------------------------------

export function getDailyReport(date?: string): Promise<DailyReport> {
  return request<DailyReport>("/reports/daily", { query: { date } });
}

// --- Copilot --------------------------------------------------------------

export function getPromociones(limite = 5): Promise<PromoCombo[]> {
  return request<PromoCombo[]>("/copilot/promociones", { query: { limite } });
}

export function getDiagnosticoHoy(date?: string): Promise<ResumenGerencial> {
  return request<ResumenGerencial>("/copilot/diagnostico-hoy", { query: { date } });
}
