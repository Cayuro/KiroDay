// Centralized single source of truth for the sale cart. All cart mutations go
// through this context's reducer; views never hold their own cart state.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";
import type { Product } from "../api/types";
import { multiplyMoney, sumMoney } from "../utils/money";

export interface CartLine {
  sku: string;
  name: string;
  /** Unit price as a decimal string, captured when added. */
  unitPrice: string;
  qty: number;
  /** Available stock, used to cap quantity on the client. */
  stock: number;
}

interface CartState {
  lines: CartLine[];
}

type CartAction =
  | { type: "ADD"; product: Product }
  | { type: "SET_QTY"; sku: string; qty: number }
  | { type: "REMOVE"; sku: string }
  | { type: "CLEAR" };

const initialState: CartState = { lines: [] };

function clampQty(qty: number, stock: number): number {
  if (qty < 1) return 1;
  if (stock > 0 && qty > stock) return stock;
  return qty;
}

function cartReducer(state: CartState, action: CartAction): CartState {
  switch (action.type) {
    case "ADD": {
      const existing = state.lines.find((line) => line.sku === action.product.sku);
      if (existing) {
        return {
          lines: state.lines.map((line) =>
            line.sku === action.product.sku
              ? { ...line, qty: clampQty(line.qty + 1, line.stock) }
              : line,
          ),
        };
      }
      // Do not add out-of-stock products.
      if (action.product.stock <= 0) {
        return state;
      }
      const newLine: CartLine = {
        sku: action.product.sku,
        name: action.product.name,
        unitPrice: action.product.price,
        qty: 1,
        stock: action.product.stock,
      };
      return { lines: [...state.lines, newLine] };
    }
    case "SET_QTY": {
      return {
        lines: state.lines.map((line) =>
          line.sku === action.sku
            ? { ...line, qty: clampQty(action.qty, line.stock) }
            : line,
        ),
      };
    }
    case "REMOVE":
      return { lines: state.lines.filter((line) => line.sku !== action.sku) };
    case "CLEAR":
      return initialState;
    default:
      return state;
  }
}

export interface CartContextValue {
  lines: CartLine[];
  itemCount: number;
  /** Cart total as a decimal string. */
  total: string;
  isEmpty: boolean;
  addProduct: (product: Product) => void;
  setQty: (sku: string, qty: number) => void;
  removeLine: (sku: string) => void;
  clear: () => void;
}

const CartContext = createContext<CartContextValue | null>(null);

export function CartProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(cartReducer, initialState);

  const addProduct = useCallback((product: Product) => dispatch({ type: "ADD", product }), []);
  const setQty = useCallback((sku: string, qty: number) => dispatch({ type: "SET_QTY", sku, qty }), []);
  const removeLine = useCallback((sku: string) => dispatch({ type: "REMOVE", sku }), []);
  const clear = useCallback(() => dispatch({ type: "CLEAR" }), []);

  const value = useMemo<CartContextValue>(() => {
    const total = sumMoney(state.lines.map((line) => multiplyMoney(line.unitPrice, line.qty)));
    const itemCount = state.lines.reduce((acc, line) => acc + line.qty, 0);
    return {
      lines: state.lines,
      itemCount,
      total,
      isEmpty: state.lines.length === 0,
      addProduct,
      setQty,
      removeLine,
      clear,
    };
  }, [state.lines, addProduct, setQty, removeLine, clear]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

/** Access the centralized cart. Throws if used outside the provider. */
export function useCart(): CartContextValue {
  const ctx = useContext(CartContext);
  if (!ctx) {
    throw new Error("useCart must be used within a CartProvider");
  }
  return ctx;
}
