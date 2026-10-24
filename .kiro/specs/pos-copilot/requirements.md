# Requirements: SmartPOS Copilot

## 1. Objetivo

Dotar al sistema POS de un copiloto inteligente que analice el inventario y recomiende promociones creativas en tiempo real para aumentar el ticket promedio.

## 2. Historias de Usuario

- **US-1**: Como cajero, al consultar promociones activas, recibo combos recomendados con productos de alto stock y el guion sugerido para decirle al cliente en el mostrador.
- **US-2**: Como dueño, puedo solicitar un diagnóstico del día con alertas de quiebre de stock y sugerencias de compra a proveedores.

## 3. Criterios de Aceptación

### US-1 — Promociones Activas
- AC-1.1: El endpoint `GET /api/copilot/promociones` devuelve una lista de `PromoCombo`.
- AC-1.2: Solo se incluyen combos con productos cuyo `stock > 10`.
- AC-1.3: El campo `pitch_cajero` contiene una frase lista para ser dicha al cliente.
- AC-1.4: Ningún combo tiene un precio inferior al 85% del precio original (margen ≥ 15%).
- AC-1.5: El campo `ahorro` es siempre `>= 0` y es un `Decimal` de 2 decimales.

### US-2 — Diagnóstico del Día
- AC-2.1: El endpoint `GET /api/copilot/diagnostico-hoy` devuelve un `ResumenGerencial`.
- AC-2.2: El campo `productos_criticos` lista los SKUs con `stock < 5`.
- AC-2.3: El campo `recomendacion_estrategica` contiene texto legible en español.
- AC-2.4: El campo `total_ventas` refleja el total del día en `Decimal` de 2 decimales.

## 4. Reglas de Negocio Aplicables

Ver `.kiro/steering/promos-rules.md` para las reglas de margen, overstock, tono y tipado.
