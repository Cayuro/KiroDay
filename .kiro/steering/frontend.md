---
inclusion: fileMatch
fileMatchPattern: "**/*.{tsx,jsx,css}"
---

# Reglas de Frontend (POS)

- Componentes funcionales con hooks; nada de componentes de clase.
- La UI debe ser usable por cajeros sin formación técnica: botones grandes,
  textos claros en español, confirmaciones antes de acciones irreversibles.
- Accesibilidad: roles ARIA y foco de teclado en formularios de cobro.
- Estado del carrito de venta centralizado (un solo lugar de verdad).
