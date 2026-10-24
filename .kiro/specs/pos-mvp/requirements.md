# Requirements Document

## Introduction

Este documento define los requisitos del MVP de un sistema de punto de venta (POS) para tiendas de barrio y cafeterías. El sistema está pensado para ser operado por personas sin conocimientos técnicos, priorizando la simplicidad sobre la completitud. El MVP cubre cuatro funcionalidades núcleo: gestión del catálogo de productos, registro de ventas con múltiples ítems, descuento atómico de inventario al registrar una venta, y el reporte de ventas del día. El idioma del producto es el español.

Los dos roles de usuario son el Cajero (registra ventas, cobra y muestra o imprime el recibo) y el Dueño (consulta reportes de ventas e inventario).

## Glossary

- **POS**: Sistema de punto de venta objeto de este documento, compuesto por una aplicación cliente y un servicio de backend.
- **Catalog_Service**: Componente del backend responsable de gestionar los productos del catálogo.
- **Sales_Service**: Componente del backend responsable de registrar ventas y coordinar el descuento de inventario.
- **Inventory_Service**: Componente del backend responsable de gestionar y actualizar el stock de los productos.
- **Report_Service**: Componente del backend responsable de generar el reporte de ventas del día.
- **Cajero**: Usuario que registra ventas, cobra y entrega el recibo al cliente.
- **Dueño**: Usuario que consulta los reportes de ventas e inventario.
- **Producto**: Ítem del catálogo definido por nombre, precio, SKU y stock.
- **SKU**: Código único que identifica un Producto dentro del catálogo (Stock Keeping Unit).
- **Stock**: Cantidad disponible de un Producto expresada como número entero no negativo.
- **Venta**: Transacción que agrupa uno o más ítems de venta, un total calculado y un método de pago.
- **Item_De_Venta**: Línea de una Venta que referencia un Producto por SKU y una cantidad vendida.
- **Metodo_De_Pago**: Forma de pago de una Venta, con valores "efectivo" o "tarjeta".
- **Recibo**: Representación de una Venta registrada que incluye los ítems, el total y el método de pago.
- **Reporte_Diario**: Resumen de las ventas registradas durante una fecha de calendario.
- **Descuento_Atomico**: Operación en la que el registro de la Venta y la reducción del Stock de todos sus ítems se confirman juntos o no se confirma ninguno.

## Requirements

### Requirement 1: Gestión del catálogo de productos

**User Story:** Como Dueño, quiero gestionar los productos del catálogo con su nombre, precio, SKU y stock, para mantener actualizada la oferta y las existencias de la tienda.

#### Acceptance Criteria

1. WHEN el Dueño envía un Producto nuevo con nombre (cadena de 1 a 100 caracteres), precio (valor decimal entre 0.01 y 999,999,999.99), SKU (cadena de 1 a 50 caracteres) y stock (entero entre 0 y 999,999), THE Catalog_Service SHALL crear el Producto y devolver su representación almacenada con nombre, precio, SKU y stock.
2. IF el Dueño envía un Producto nuevo cuyo SKU ya existe en el catálogo, THEN THE Catalog_Service SHALL rechazar la creación, no modificar el Producto existente y devolver un error que indique SKU duplicado.
3. IF el Dueño envía un Producto nuevo con precio fuera del rango 0.01 a 999,999,999.99 o con stock fuera del rango 0 a 999,999, THEN THE Catalog_Service SHALL rechazar la creación y devolver un error de validación que indique el campo inválido.
4. IF el Dueño envía un Producto nuevo con nombre vacío, con nombre que excede 100 caracteres, o con SKU vacío o que excede 50 caracteres, THEN THE Catalog_Service SHALL rechazar la creación y devolver un error de validación que indique el campo inválido.
5. WHEN el Dueño solicita la lista de productos, THE Catalog_Service SHALL devolver todos los productos del catálogo, cada uno con su nombre, precio, SKU y stock.
6. WHEN el Dueño solicita la lista de productos y el catálogo no contiene ningún Producto, THE Catalog_Service SHALL devolver una lista vacía.
7. WHEN el Dueño actualiza el nombre (cadena de 1 a 100 caracteres), el precio (valor decimal entre 0.01 y 999,999,999.99) o el stock (entero entre 0 y 999,999) de un Producto existente identificado por SKU, THE Catalog_Service SHALL guardar los valores actualizados y devolver la representación resultante.
8. IF el Dueño solicita actualizar un Producto con un SKU que no existe en el catálogo, THEN THE Catalog_Service SHALL rechazar la actualización, no crear ningún Producto nuevo y devolver un error que indique Producto no encontrado.
9. IF el Dueño actualiza un Producto existente con un precio fuera del rango 0.01 a 999,999,999.99 o con un stock fuera del rango 0 a 999,999, THEN THE Catalog_Service SHALL rechazar la actualización, conservar los valores previos del Producto y devolver un error de validación que indique el campo inválido.

### Requirement 2: Registro de una venta

**User Story:** Como Cajero, quiero registrar una venta con varios ítems, su total y el método de pago, para cobrar al cliente y dejar constancia de la transacción.

#### Acceptance Criteria

1. WHEN el Cajero registra una Venta con 1 a 100 ítems, donde cada ítem referencia un SKU existente y una cantidad entera entre 1 y 9999, THE Sales_Service SHALL registrar la Venta y devolver su identificador único junto con el total calculado.
2. THE Sales_Service SHALL calcular el total de la Venta como la suma de los subtotales de cada Item_De_Venta, donde el subtotal es el precio del Producto multiplicado por la cantidad vendida, redondeado a 2 decimales, en el rango de 0.01 a 999,999,999.99.
3. WHEN el Cajero registra una Venta, THE Sales_Service SHALL almacenar el Metodo_De_Pago con valor "efectivo" o "tarjeta".
4. WHEN el Sales_Service registra una Venta, THE Sales_Service SHALL almacenar la fecha y hora de la transacción en el momento del registro.
5. IF el Cajero registra una Venta con un Item_De_Venta cuyo SKU no existe en el catálogo, THEN THE Sales_Service SHALL rechazar la Venta sin persistir ningún dato y devolver un error que indique SKU inexistente, incluyendo el SKU rechazado.
6. IF el Cajero registra una Venta sin ítems, THEN THE Sales_Service SHALL rechazar la Venta sin persistir ningún dato y devolver un error de validación que indique que se requiere al menos un ítem.
7. IF el Cajero registra una Venta con un Item_De_Venta cuya cantidad no es un entero entre 1 y 9999, THEN THE Sales_Service SHALL rechazar la Venta sin persistir ningún dato y devolver un error de validación que indique cantidad inválida.
8. IF el Cajero registra una Venta con un Metodo_De_Pago distinto de "efectivo" o "tarjeta", THEN THE Sales_Service SHALL rechazar la Venta sin persistir ningún dato y devolver un error de validación que indique método de pago inválido.

### Requirement 3: Descuento atómico de stock al registrar una venta

**User Story:** Como Dueño, quiero que el stock se descuente de forma atómica al registrar una venta, para que el inventario refleje siempre las existencias reales sin ventas que dejen el stock inconsistente.

#### Acceptance Criteria

1. WHEN el Sales_Service registra una Venta cuyos ítems tienen Stock suficiente (Stock disponible mayor o igual que la cantidad solicitada para cada Producto), THE Inventory_Service SHALL reducir el Stock de cada Producto vendido en la cantidad del Item_De_Venta correspondiente, dejando el Stock resultante en un valor entero mayor o igual que 0.
2. WHEN el Sales_Service registra una Venta, THE Sales_Service SHALL confirmar el registro de la Venta y el descuento del Stock de todos sus ítems como un Descuento_Atomico, de modo que ambos efectos se apliquen por completo o ninguno se aplique.
3. IF al registrar una Venta el Stock disponible de al menos un Producto es menor que la cantidad solicitada, THEN THE Sales_Service SHALL rechazar la Venta completa, no registrar ningún Item_De_Venta y devolver un error que indique stock insuficiente e identifique cada Producto cuyo Stock disponible es menor que la cantidad solicitada.
4. IF el Sales_Service rechaza una Venta por stock insuficiente, THEN THE Inventory_Service SHALL conservar el Stock de todos los Productos con exactamente los valores previos al intento de Venta.
5. IF la confirmación del Descuento_Atomico falla durante el registro de una Venta, THEN THE Sales_Service SHALL revertir el registro de la Venta, conservar el Stock de todos los Productos con exactamente los valores previos al intento de Venta y devolver un error que indique que el registro no se completó.
6. WHILE dos o más solicitudes de Venta se procesan de forma concurrente y compiten por el Stock del mismo Producto, THE Inventory_Service SHALL confirmar como máximo el conjunto de Ventas cuya suma de cantidades solicitadas para ese Producto no supere el Stock disponible previo, y rechazar las restantes con un error que indique stock insuficiente.
7. WHEN una solicitud de Venta es rechazada por concurrencia sobre el Stock de un Producto, THE Sales_Service SHALL no registrar la Venta rechazada ni modificar el Stock de ningún Producto por efecto de esa solicitud.

### Requirement 4: Reporte de ventas del día

**User Story:** Como Dueño, quiero ver el reporte de ventas del día, para conocer cuánto se vendió y controlar el movimiento de la tienda.

#### Acceptance Criteria

1. WHEN el Dueño solicita el Reporte_Diario para una fecha válida en formato de calendario (año-mes-día), THE Report_Service SHALL devolver la cantidad total de ventas registradas en esa fecha como un entero mayor o igual a cero y la suma de sus totales como un valor monetario entre 0.00 y 999,999,999.99.
2. WHEN el Dueño solicita el Reporte_Diario para una fecha válida, THE Report_Service SHALL incluir el total vendido desglosado por cada Metodo_De_Pago, mostrando cada Metodo_De_Pago con al menos una venta registrada en esa fecha con su suma de totales correspondiente.
3. IF el Dueño solicita el Reporte_Diario para una fecha válida sin ventas registradas, THEN THE Report_Service SHALL devolver una cantidad total de ventas igual a cero, una suma de totales igual a 0.00 y un desglose por Metodo_De_Pago vacío.
4. WHERE el Dueño no especifica una fecha al solicitar el Reporte_Diario, THE Report_Service SHALL generar el reporte para la fecha actual del sistema.
5. IF el Dueño solicita el Reporte_Diario con una fecha con formato inválido o con una fecha futura respecto a la fecha actual del sistema, THEN THE Report_Service SHALL rechazar la solicitud, conservar sin cambios los datos de ventas y devolver un mensaje de error indicando que la fecha es inválida.
