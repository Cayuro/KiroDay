---
name: smart-pos-copilot
version: 1.0.0
description: Kit integral de agentes y skills para convertir cualquier POS en un copiloto de ventas y retail marketing.
author: KiroDay Team
---

# SmartPOS Copilot Power

Este Power empaqueta todo lo necesario para añadir inteligencia de ventas a un POS construido con FastAPI + DynamoDB.

## Componentes incluidos

- **Agentes**: `promo-creator` — estratega de retail que genera combos y pitches creativos.
- **Skills**: `retail-strategy` — manual de técnicas de venta cruzada y fórmulas de descuento.
- **Steering**: `promos-rules` — reglas de margen, overstock, tono y tipado estricto.
- **Hooks**: `qa-copilot` — validación automática de sintaxis al modificar `copilot.py`.

## Cómo usar este Power

1. Copia la carpeta `.kiro/` a tu proyecto POS.
2. Instala las dependencias del backend: `pip install -e ".[dev]"`.
3. Arranca la API: `uvicorn app.api.app:app --reload`.
4. Consulta las promociones: `GET /api/copilot/promociones`.
5. Consulta el diagnóstico del día: `GET /api/copilot/diagnostico-hoy`.

## Arquitectura del Copilot

```
CopilotService
├── generar_promociones()  →  list[PromoCombo]
└── analisis_gerencial()   →  ResumenGerencial
```

## Reglas de Negocio Clave

- Margen mínimo protegido: **15%** sobre precio de venta.
- Overstock threshold: **stock > 10** para candidatos a combo.
- Stock crítico: **stock < 5** dispara alerta gerencial.
- Dinero siempre con `Decimal`, nunca `float`.
