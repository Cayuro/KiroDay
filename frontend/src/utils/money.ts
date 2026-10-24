// Money helpers. Prices arrive as decimal strings; we keep arithmetic in a
// scaled-integer (cents) domain so we never introduce binary-float rounding,
// mirroring the backend's Decimal discipline.

/** Parse a decimal string like "1500.50" into integer cents (150050). */
export function toCents(amount: string): number {
  const normalized = amount.trim();
  const negative = normalized.startsWith("-");
  const unsigned = negative ? normalized.slice(1) : normalized;
  const [whole, fraction = ""] = unsigned.split(".");
  const cents = fraction.padEnd(2, "0").slice(0, 2);
  const value = Number.parseInt(whole || "0", 10) * 100 + Number.parseInt(cents || "0", 10);
  return negative ? -value : value;
}

/** Format integer cents back into a decimal string like "1500.50". */
export function fromCents(cents: number): string {
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const frac = (abs % 100).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${frac}`;
}

/** Format a decimal money string for display, e.g. "$1.500,50" (es-CO style). */
export function formatMoney(amount: string): string {
  const cents = toCents(amount);
  const value = cents / 100;
  return new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/** Sum a list of decimal strings via cents and return a decimal string. */
export function sumMoney(amounts: string[]): string {
  const total = amounts.reduce((acc, amount) => acc + toCents(amount), 0);
  return fromCents(total);
}

/** Multiply a decimal money string by an integer quantity (decimal string). */
export function multiplyMoney(amount: string, qty: number): string {
  return fromCents(toCents(amount) * qty);
}
