# Design Document: SmartPOS Copilot

## Arquitectura

```
GET /api/copilot/promociones
GET /api/copilot/diagnostico-hoy
        │
        ▼
  routes.py (thin adapter)
        │
        ▼
  CopilotService
  ├── CatalogService  (lee catálogo de productos)
  └── ReportService   (lee ventas del día)
        │
        ▼
  PosRepository (InMemory / DynamoDB)
```

## Nuevos Componentes

### `backend/app/models/copilot.py`

```python
@dataclass(frozen=True)
class PromoCombo:
    nombre: str
    skus: list[str]
    precio_original: Decimal   # suma de precios unitarios
    precio_combo: Decimal      # precio con descuento aplicado
    ahorro: Decimal            # precio_original - precio_combo
    pitch_cajero: str          # frase lista para el mostrador

@dataclass(frozen=True)
class ResumenGerencial:
    fecha: str                         # YYYY-MM-DD
    total_ventas: Decimal              # total del día
    productos_criticos: list[str]      # SKUs con stock < 5
    recomendacion_estrategica: str     # texto libre en español
```

### `backend/app/services/copilot.py`

```python
class CopilotService:
    def __init__(self, catalog: CatalogService, report: ReportService) -> None: ...
    def generar_promociones(self, limite_combos: int = 5) -> list[PromoCombo]: ...
    def analisis_gerencial(self, fecha: str | None = None) -> ResumenGerencial: ...
```

**Lógica de `generar_promociones`**:
1. Obtener todos los productos con `CatalogService.list_products()`.
2. Filtrar productos con `stock > 10` (candidatos a overstock).
3. Si hay ≥ 2 candidatos, ordenar por precio descendente y armar combos
   emparejando el más caro con el más barato.
4. Calcular `precio_combo = precio_original * Decimal("0.90")` (10% off).
5. Validar que `precio_combo >= precio_original * Decimal("0.85")` (margen ≥ 15%).
6. Generar `pitch_cajero` con la plantilla de `retail-strategy`.
7. Retornar hasta `limite_combos` combos.

**Lógica de `analisis_gerencial`**:
1. Llamar a `ReportService.daily_report(fecha)` para el total del día.
2. Obtener todos los productos y filtrar los que tienen `stock < 5`.
3. Generar `recomendacion_estrategica` basada en los datos.

## Endpoints Nuevos (`backend/app/api/routes.py`)

| Método | Path | Descripción |
|--------|------|-------------|
| `GET` | `/api/copilot/promociones` | Lista de combos dinámicos sugeridos |
| `GET` | `/api/copilot/diagnostico-hoy` | Métricas clave y recomendaciones de inventario |

## Inyección de Dependencias (`backend/app/api/deps.py`)

```python
def get_copilot_service(
    catalog: CatalogService = Depends(get_catalog_service),
    report: ReportService = Depends(get_report_service),
) -> CopilotService:
    return CopilotService(catalog, report)
```

## Schemas de Respuesta (`backend/app/api/schemas.py`)

```python
class PromoComboResponse(BaseModel):
    nombre: str
    skus: list[str]
    precio_original: str   # Decimal como string
    precio_combo: str
    ahorro: str
    pitch_cajero: str

class ResumenGerencialResponse(BaseModel):
    fecha: str
    total_ventas: str
    productos_criticos: list[str]
    recomendacion_estrategica: str
```
