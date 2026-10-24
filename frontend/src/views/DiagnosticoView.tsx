// Copilot diagnostic view (US-2, owner): shows today's total sales, a list of
// critical (stock-break-risk) products, and the strategic recommendation.

import { useEffect, useState } from "react";
import { ApiError, getDiagnosticoHoy } from "../api";
import type { ResumenGerencial } from "../api/types";
import { StatusBanner } from "../components/StatusBanner";
import { formatMoney } from "../utils/money";

export function DiagnosticoView() {
  const [resumen, setResumen] = useState<ResumenGerencial | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setResumen(await getDiagnosticoHoy());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo cargar el diagnóstico.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="view">
      <h1>Diagnóstico del día</h1>
      <p className="view-intro">Resumen para el dueño: ventas, alertas de stock y recomendación.</p>

      <div className="toolbar">
        <button type="button" className="btn btn-secondary" onClick={() => void load()}>
          Actualizar
        </button>
      </div>

      {loading && <StatusBanner kind="info" message="Cargando diagnóstico…" />}
      {error && <StatusBanner kind="error" message={error} />}

      {!loading && !error && resumen && (
        <>
          <section className="card metric-card" aria-labelledby="total-heading">
            <h2 id="total-heading">Ventas de hoy ({resumen.fecha})</h2>
            <p className="metric-value">{formatMoney(resumen.total_ventas)}</p>
          </section>

          <section className="card" aria-labelledby="critical-heading">
            <h2 id="critical-heading">Productos críticos (riesgo de quiebre de stock)</h2>
            {resumen.productos_criticos.length === 0 ? (
              <p className="empty">Sin alertas de stock. Todo en orden.</p>
            ) : (
              <ul className="critical-list">
                {resumen.productos_criticos.map((sku) => (
                  <li key={sku} className="critical-item">
                    <span className="tag tag-danger">⚠ {sku}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card recommendation" aria-labelledby="reco-heading">
            <h2 id="reco-heading">Recomendación estratégica</h2>
            <p className="reco-text">{resumen.recomendacion_estrategica}</p>
          </section>
        </>
      )}
    </div>
  );
}
