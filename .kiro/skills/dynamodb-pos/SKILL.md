---
name: dynamodb-pos
description: Modela los datos del POS (productos, ventas, inventario) en Amazon DynamoDB con diseño de tabla única. Úsala al diseñar el esquema de datos, claves de partición/orden, o patrones de acceso del POS.
---

# Modelado del POS en DynamoDB (tabla única)

## Patrones de acceso (primero esto, SIEMPRE)
1. Obtener un producto por SKU.
2. Listar todos los productos (catálogo).
3. Registrar una venta con varios ítems.
4. Listar las ventas de un día.

## Diseño de tabla única
Una sola tabla `pos` con claves genéricas `PK` y `SK`.

| Entidad   | PK                | SK                      | Atributos                         |
|-----------|-------------------|-------------------------|-----------------------------------|
| Producto  | `PRODUCT#<sku>`   | `PRODUCT#<sku>`         | name, price, stock                |
| Venta     | `SALE#<date>`     | `SALE#<ts>#<saleId>`    | total, paymentMethod, items[]     |

## Reglas
- Descontar `stock` del producto en la misma operación de venta (transacción).
- Fechas en ISO-8601 UTC para ordenar ventas por `SK`.
- No normalizar en exceso: en DynamoDB se modela por patrón de acceso, no por
  relaciones.

## Antipatrones a evitar
- Scan para listar el catálogo si crece mucho (preferir Query por prefijo).
- Guardar el total como string (usar número para poder sumar en reportes).
