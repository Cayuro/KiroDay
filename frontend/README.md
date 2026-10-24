# SmartPOS Copilot — Frontend

Interfaz de punto de venta (POS) en **React + Vite + TypeScript**, pensada para
cajeros sin formación técnica: botones grandes, textos en español y confirmación
antes de acciones irreversibles (cobrar una venta).

## Requisitos

- Node.js 18+ (probado con Node 22)
- El backend FastAPI corriendo (por defecto en `http://localhost:8000`)

## Cómo correr en local

```bash
npm install
npm run dev
```

Vite sirve la app en `http://localhost:5173`.

## Configurar la URL del backend

La app lee la base URL desde la variable de entorno `VITE_API_BASE_URL`.
Si no se define, usa `http://localhost:8000`.

Crea un archivo `.env.local` (no se versiona) a partir del ejemplo:

```bash
cp .env.example .env.local
```

```
VITE_API_BASE_URL=http://localhost:8000
```

No pongas secretos aquí: solo la URL pública del API.

> **Nota CORS:** el backend FastAPI aún no habilita CORS. Para desarrollo con
> frontend y backend en puertos distintos, agrega `CORSMiddleware` en el backend
> o sirve ambos tras el mismo origen.

## Build de producción

```bash
npm run build
```

- Ejecuta el chequeo de tipos (`tsc -b`) y genera la salida estática en `dist/`.
- Previsualiza el build con `npm run preview`.

## Despliegue en AWS Amplify Hosting

- **Build command:** `npm run build`
- **Output directory (baseDirectory):** `dist`
- Define `VITE_API_BASE_URL` como variable de entorno en la consola de Amplify
  apuntando al endpoint del API Gateway del backend.

## Estructura

```
src/
  api/        Capa de API tipada (cliente fetch + tipos + error envelope)
  cart/       Estado centralizado del carrito (Context + useCart)
  components/ Componentes compartidos (diálogo de confirmación, banner)
  utils/      Utilidades de dinero (Decimal como string, sin float)
  views/      Pantallas: Catálogo, Venta, Promociones, Diagnóstico
```

## Vistas

- **Catálogo:** lista productos con stock y permite dar de alta un producto.
- **Venta:** carrito centralizado, total en vivo, método de pago y cobro con
  diálogo de confirmación; muestra el recibo tras la venta.
- **Promociones (Copilot / cajero):** combos sugeridos con ahorro, precios y el
  `pitch_cajero` resaltado para leer al cliente (US-1).
- **Diagnóstico (Copilot / dueño):** total del día, productos críticos y
  recomendación estratégica (US-2).
