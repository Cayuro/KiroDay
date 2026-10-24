---
name: retail-strategy
description: Estrategias de promociones, venta cruzada (cross-selling) y optimización de inventario en retail.
---

# Retail Strategy & Promotion Engineering

## 1. Técnicas de Venta Cruzada

- **Bundle Complementario**: Asociar producto de consumo frecuente (ej: café) con producto de impulso (ej: galleta o snack) con un pequeño descuento en el combo.
- **2x1 Condicional**: Segundo producto con 50% de descuento si el inventario supera las 50 unidades.

## 2. Fórmulas de Cálculo

- `Margen = (Precio_Venta - Costo) / Precio_Venta`
- `Ticket Promedio = Total_Ventas / Cantidad_Transacciones`
- `Descuento Sugerido = min(Margen_Disponible * 0.5, Descuento_Maximo_Permitido)`
- `Margen Mínimo = 15%` — ninguna promo puede perforar este piso.

## 3. Generación de Frase para el Cajero

Estructura recomendada:
`[Saludo empático] + [Oferta de oportunidad] + [Beneficio directo]`.

Ejemplo: *"¿Gusta llevar las galletas de avena por solo $1.000 más para acompañar su café?"*

## 4. Regla de Overstock

Productos con `stock > 10` son candidatos prioritarios para combos. Si hay dos o más candidatos, se crea un combo mezclando el más costoso con el más económico para maximizar el valor percibido por el cliente.

## 5. Protección de Margen

El precio combo nunca puede resultar en un margen inferior al 15% del precio de venta original. Fórmula de validación:

```
precio_combo >= precio_original * Decimal("0.85")
```
