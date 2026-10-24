// Copilot promotions view (US-1, cashier): shows suggested combos with name,
// savings, prices, and the `pitch_cajero` highlighted so the cashier can read
// it aloud to the customer at the counter.

import { useEffect, useState } from "react";
import { ApiError, getPromociones } from "../api";
import type { PromoCombo } from "../api/types";
import { StatusBanner } from "../components/StatusBanner";
import { formatMoney } from "../utils/money";

export function PromosView() {
  const [combos, setCombos] = useState<PromoCombo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setCombos(await getPromociones(5));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudieron cargar las promociones.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="view">
      <h1>Promociones sugeridas</h1>
      <p className="view-intro">
        Combos recomendados para ofrecer en el mostrador. Lee el mensaje resaltado al cliente.
      </p>

      <div className="toolbar">
        <button type="button" className="btn btn-secondary" onClick={() => void load()}>
          Actualizar sugerencias
        </button>
      </div>

      {loading && <StatusBanner kind="info" message="Cargando promociones…" />}
      {error && <StatusBanner kind="error" message={error} />}
      {!loading && !error && combos.length === 0 && (
        <p className="empty">No hay promociones sugeridas por ahora.</p>
      )}

      <div className="promo-grid">
        {combos.map((combo, index) => (
          <article className="card promo-card" key={`${combo.nombre}-${index}`}>
            <h2 className="promo-name">{combo.nombre}</h2>

            <p className="promo-skus">
              <span className="muted">Productos:</span> {combo.skus.join(" + ")}
            </p>

            <div className="promo-prices">
              <span className="price-original">{formatMoney(combo.precio_original)}</span>
              <span className="price-combo">{formatMoney(combo.precio_combo)}</span>
            </div>
            <p className="promo-saving">Ahorro: {formatMoney(combo.ahorro)}</p>

            <blockquote className="pitch" aria-label="Mensaje para decir al cliente">
              <span className="pitch-label">Dile al cliente:</span>
              “{combo.pitch_cajero}”
            </blockquote>
          </article>
        ))}
      </div>
    </div>
  );
}
