// Catalog view: lists products with stock and lets the user create a product.
// Adding a product to the cart is delegated to the centralized cart context.

import { useEffect, useState, type FormEvent } from "react";
import { ApiError, createProduct, listProducts } from "../api";
import type { Product } from "../api/types";
import { useCart } from "../cart/CartContext";
import { StatusBanner } from "../components/StatusBanner";
import { formatMoney } from "../utils/money";

export function CatalogView() {
  const { addProduct } = useCart();
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // New-product form fields.
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [stock, setStock] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  async function loadProducts() {
    setLoading(true);
    setError(null);
    try {
      setProducts(await listProducts());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudieron cargar los productos.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadProducts();
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setFormSuccess(null);

    if (!sku.trim() || !name.trim() || !price.trim() || !stock.trim()) {
      setFormError("Completa todos los campos para dar de alta el producto.");
      return;
    }

    setSaving(true);
    try {
      await createProduct({
        sku: sku.trim(),
        name: name.trim(),
        price: price.trim(),
        stock: Number.parseInt(stock, 10),
      });
      setFormSuccess(`Producto "${name.trim()}" agregado al catálogo.`);
      setSku("");
      setName("");
      setPrice("");
      setStock("");
      await loadProducts();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "No se pudo crear el producto.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="view">
      <h1>Catálogo</h1>

      <section aria-labelledby="new-product-heading" className="card">
        <h2 id="new-product-heading">Agregar producto</h2>
        <form className="form-grid" onSubmit={handleCreate}>
          <div className="field">
            <label htmlFor="field-sku">Código (SKU)</label>
            <input
              id="field-sku"
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="field">
            <label htmlFor="field-name">Nombre</label>
            <input id="field-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="field-price">Precio</label>
            <input
              id="field-price"
              inputMode="decimal"
              placeholder="1500.00"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="field-stock">Stock</label>
            <input
              id="field-stock"
              inputMode="numeric"
              placeholder="0"
              value={stock}
              onChange={(e) => setStock(e.target.value)}
            />
          </div>
          <div className="field field-actions">
            <button type="submit" className="btn btn-primary btn-lg" disabled={saving}>
              {saving ? "Guardando…" : "Agregar producto"}
            </button>
          </div>
        </form>
        {formError && <StatusBanner kind="error" message={formError} />}
        {formSuccess && <StatusBanner kind="success" message={formSuccess} />}
      </section>

      <section aria-labelledby="product-list-heading" className="card">
        <h2 id="product-list-heading">Productos</h2>
        {loading && <StatusBanner kind="info" message="Cargando productos…" />}
        {error && <StatusBanner kind="error" message={error} />}
        {!loading && !error && products.length === 0 && (
          <p className="empty">Aún no hay productos. Agrega el primero arriba.</p>
        )}
        {!loading && !error && products.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">SKU</th>
                <th scope="col">Nombre</th>
                <th scope="col">Precio</th>
                <th scope="col">Stock</th>
                <th scope="col">Acción</th>
              </tr>
            </thead>
            <tbody>
              {products.map((product) => {
                const outOfStock = product.stock <= 0;
                return (
                  <tr key={product.sku}>
                    <td>{product.sku}</td>
                    <td>{product.name}</td>
                    <td>{formatMoney(product.price)}</td>
                    <td>
                      {outOfStock ? (
                        <span className="tag tag-danger">Sin stock</span>
                      ) : (
                        product.stock
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => addProduct(product)}
                        disabled={outOfStock}
                        aria-label={`Agregar ${product.name} al carrito`}
                      >
                        Agregar al carrito
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
