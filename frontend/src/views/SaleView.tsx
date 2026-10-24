// Sale view: shows the centralized cart with a live total, payment method
// selection, and a confirmation dialog before charging (an irreversible
// action). After a successful sale it renders the receipt.

import { useState } from "react";
import { ApiError, registerSale } from "../api";
import type { PaymentMethod, Sale } from "../api/types";
import { useCart } from "../cart/CartContext";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { StatusBanner } from "../components/StatusBanner";
import { formatMoney, multiplyMoney } from "../utils/money";

const PAYMENT_LABELS: Record<PaymentMethod, string> = {
  efectivo: "Efectivo",
  tarjeta: "Tarjeta",
};

export function SaleView() {
  const { lines, total, isEmpty, setQty, removeLine, clear } = useCart();
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("efectivo");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [charging, setCharging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<Sale | null>(null);

  async function handleConfirmCharge() {
    setCharging(true);
    setError(null);
    try {
      const sale = await registerSale({
        items: lines.map((line) => ({ sku: line.sku, qty: line.qty })),
        payment_method: paymentMethod,
      });
      setReceipt(sale);
      clear();
      setConfirmOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo registrar la venta.");
      setConfirmOpen(false);
    } finally {
      setCharging(false);
    }
  }

  // Receipt screen after a completed sale.
  if (receipt) {
    return (
      <div className="view">
        <h1>Recibo</h1>
        <section className="card receipt" aria-labelledby="receipt-heading">
          <h2 id="receipt-heading">Venta registrada</h2>
          <p className="receipt-meta">
            <strong>N.º venta:</strong> {receipt.sale_id}
          </p>
          <p className="receipt-meta">
            <strong>Fecha:</strong> {new Date(receipt.timestamp).toLocaleString("es-CO")}
          </p>
          <p className="receipt-meta">
            <strong>Método de pago:</strong> {PAYMENT_LABELS[receipt.payment_method]}
          </p>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Producto</th>
                <th scope="col">Cant.</th>
                <th scope="col">Precio</th>
                <th scope="col">Subtotal</th>
              </tr>
            </thead>
            <tbody>
              {receipt.items.map((item) => (
                <tr key={item.sku}>
                  <td>{item.sku}</td>
                  <td>{item.qty}</td>
                  <td>{formatMoney(item.unit_price)}</td>
                  <td>{formatMoney(item.subtotal)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="receipt-total">Total: {formatMoney(receipt.total)}</p>
          <button
            type="button"
            className="btn btn-primary btn-lg"
            onClick={() => setReceipt(null)}
          >
            Nueva venta
          </button>
        </section>
      </div>
    );
  }

  return (
    <div className="view">
      <h1>Venta</h1>

      {error && <StatusBanner kind="error" message={error} />}

      <section className="card" aria-labelledby="cart-heading">
        <h2 id="cart-heading">Carrito</h2>
        {isEmpty ? (
          <p className="empty">
            El carrito está vacío. Ve al Catálogo y agrega productos para cobrar.
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Producto</th>
                <th scope="col">Precio</th>
                <th scope="col">Cantidad</th>
                <th scope="col">Subtotal</th>
                <th scope="col">Quitar</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.sku}>
                  <td>{line.name}</td>
                  <td>{formatMoney(line.unitPrice)}</td>
                  <td>
                    <input
                      type="number"
                      className="qty-input"
                      min={1}
                      max={line.stock > 0 ? line.stock : undefined}
                      value={line.qty}
                      aria-label={`Cantidad de ${line.name}`}
                      onChange={(e) => setQty(line.sku, Number.parseInt(e.target.value, 10) || 1)}
                    />
                  </td>
                  <td>{formatMoney(multiplyMoney(line.unitPrice, line.qty))}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => removeLine(line.sku)}
                      aria-label={`Quitar ${line.name} del carrito`}
                    >
                      Quitar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {!isEmpty && (
        <section className="card checkout" aria-labelledby="checkout-heading">
          <h2 id="checkout-heading">Cobrar</h2>
          <fieldset className="payment-methods">
            <legend>Método de pago</legend>
            {(Object.keys(PAYMENT_LABELS) as PaymentMethod[]).map((method) => (
              <label key={method} className="radio-option">
                <input
                  type="radio"
                  name="payment-method"
                  value={method}
                  checked={paymentMethod === method}
                  onChange={() => setPaymentMethod(method)}
                />
                {PAYMENT_LABELS[method]}
              </label>
            ))}
          </fieldset>

          <p className="checkout-total" aria-live="polite">
            Total a cobrar: <strong>{formatMoney(total)}</strong>
          </p>

          <button
            type="button"
            className="btn btn-primary btn-xl"
            onClick={() => setConfirmOpen(true)}
          >
            Cobrar {formatMoney(total)}
          </button>
        </section>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title="Confirmar cobro"
        message={`Vas a registrar una venta por ${formatMoney(total)} pagada con ${PAYMENT_LABELS[paymentMethod]}. Esta acción descuenta el stock y no se puede deshacer. ¿Continuar?`}
        confirmLabel="Sí, cobrar"
        cancelLabel="Cancelar"
        busy={charging}
        onConfirm={handleConfirmCharge}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
