// Root app: simple tab navigation between the four views. The cart badge in the
// nav reads from the centralized cart context.

import { useState } from "react";
import { useCart } from "./cart/CartContext";
import { CatalogView } from "./views/CatalogView";
import { SaleView } from "./views/SaleView";
import { PromosView } from "./views/PromosView";
import { DiagnosticoView } from "./views/DiagnosticoView";

type Tab = "catalog" | "sale" | "promos" | "diagnostico";

const TABS: { id: Tab; label: string }[] = [
  { id: "catalog", label: "Catálogo" },
  { id: "sale", label: "Venta" },
  { id: "promos", label: "Promociones" },
  { id: "diagnostico", label: "Diagnóstico" },
];

export function App() {
  const [tab, setTab] = useState<Tab>("catalog");
  const { itemCount } = useCart();

  return (
    <div className="app">
      <header className="app-header">
        <span className="brand">SmartPOS Copilot</span>
        <nav className="tabs" aria-label="Secciones">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              className={`tab ${tab === id ? "tab-active" : ""}`}
              aria-current={tab === id ? "page" : undefined}
              onClick={() => setTab(id)}
            >
              {label}
              {id === "sale" && itemCount > 0 && (
                <span className="cart-badge" aria-label={`${itemCount} artículos en el carrito`}>
                  {itemCount}
                </span>
              )}
            </button>
          ))}
        </nav>
      </header>

      <main className="app-main">
        {tab === "catalog" && <CatalogView />}
        {tab === "sale" && <SaleView />}
        {tab === "promos" && <PromosView />}
        {tab === "diagnostico" && <DiagnosticoView />}
      </main>
    </div>
  );
}
