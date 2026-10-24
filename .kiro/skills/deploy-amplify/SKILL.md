---
name: deploy-amplify
description: Despliega el POS con AWS Amplify — hosting del frontend React, backend (API/datos) y CI/CD desde el repo. Úsala al publicar, desplegar o configurar hosting del POS.
---

# Desplegar el POS con AWS Amplify

## Cuándo usar Amplify
Para publicar rápido una app full-stack (frontend + backend + auth + datos) con
CI/CD conectado al repositorio, sin gestionar servidores.

## Flujo de despliegue del frontend (React + Vite)
1. `npm create vite@latest` ya debe existir (lo crea frontend-dev).
2. Conectar el repo en Amplify Hosting (build automático en cada push).
3. Build settings típicos para Vite:
   - build command: `npm run build`
   - output directory: `dist`

## Backend (datos + API)
- Con Amplify Gen 2 (TypeScript, code-first) se definen datos (DynamoDB vía
  AppSync) y funciones. Encaja con el stack del POS.
- Alternativa: mantener FastAPI en Lambda + API Gateway y usar Amplify solo
  para el hosting del frontend. Decidir con el arquitecto según complejidad.

## Checklist antes de publicar
- Variables de entorno y endpoints del backend configurados en Amplify.
- Dominio: usar el de Amplify al inicio; dominio propio después.
- Revisar costos: hosting + requests + almacenamiento de datos.

## Nota
Este proyecto tiene un skill/power de Amplify Gen2 más completo disponible en el
entorno; esta skill es la guía de arranque específica del POS.
