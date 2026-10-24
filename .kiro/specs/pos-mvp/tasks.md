# Implementation Plan: POS MVP

## Overview

This plan implements the POS MVP in Python 3.12 + FastAPI with an Amazon DynamoDB
single-table design, a React + Vite + TypeScript frontend, and AWS SAM for infrastructure,
as fixed by the project steering and `design.md`.

The plan is ordered strictly by dependency so each step builds on the previous one with no
orphaned code:

1. Project scaffolding and shared types.
2. Domain models and validation (pure, no I/O).
3. DynamoDB repository plus an in-memory transactional fake that reproduces
   `TransactWriteItems` all-or-nothing semantics for tests.
4. Services: `Catalog_Service`, then `Sales_Service` + `Inventory_Service` (the atomic
   stock discount — the most delicate part), then `Report_Service`.
5. FastAPI API layer (routing, error envelope, dependency wiring).
6. React + Vite + TypeScript frontend (optional for the MVP core).
7. AWS SAM infrastructure (optional for the MVP core).

Business logic and its tests are the required core. The 14 correctness properties from
`design.md` are each implemented as a Hypothesis property-based test running a minimum of
100 iterations (`@settings(max_examples=100)` or higher), complemented by example-based unit
tests and a small set of integration tests against DynamoDB Local.

Special care is taken with the **atomic stock discount** (Requirement 3 / Properties 8–11):
the transactional fake must faithfully reproduce DynamoDB `TransactWriteItems` semantics, and
the real behavior is pinned down with DynamoDB Local integration tests.

## Tasks

- [ ] 1. Set up backend project structure and shared foundations
  - Create the backend package layout: `backend/app/{models,repository,services,api}/`,
    `backend/tests/{unit,property,integration}/`.
  - Add `pyproject.toml` (Python 3.12) with dependencies: `fastapi`, `mangum`, `boto3`,
    `pydantic`, and dev dependencies `pytest`, `hypothesis`, `moto`/DynamoDB-Local tooling.
  - Define shared primitives used everywhere: a `Decimal`-based money type/helpers,
    a JSON error envelope `{ "error": { "code", "message", "details" } }`, and the
    `ErrorCode` enum (`VALIDATION_ERROR`, `DUPLICATE_SKU`, `PRODUCT_NOT_FOUND`,
    `UNKNOWN_SKU`, `INSUFFICIENT_STOCK`, `TRANSACTION_FAILED`, `INVALID_DATE`,
    `INTERNAL_ERROR`).
  - Configure the testing framework and a Hypothesis profile with `max_examples>=100`.
  - _Requirements: 1.1, 2.2, 3.3_

- [ ] 2. Implement domain models and validation
  - [ ] 2.1 Implement `Product` model and validation
    - Define the `Product` model (`sku`, `name`, `price` as `Decimal`, `stock` as `int`).
    - Enforce ranges: `name` length 1–100, `price` in `[0.01, 999999999.99]`,
      `sku` length 1–50, `stock` in `[0, 999999]`; raise a validation error naming the
      offending field. Use `Decimal` for money, never binary float.
    - _Requirements: 1.1, 1.3, 1.4_

  - [ ]* 2.2 Write property test: create round-trip preserves fields
    - **Property 1: Create round-trip preserves fields**
    - **Validates: Requirements 1.1**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 1`.

  - [ ]* 2.3 Write property test: invalid create is rejected
    - **Property 2: Invalid create is rejected and persists nothing** (validation half:
      out-of-range price/stock, empty/over-long name, empty/over-long sku).
    - **Validates: Requirements 1.2, 1.3, 1.4**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 2`.

  - [ ] 2.4 Implement `Sale`, `SaleItem`, and sale validation and total calculation
    - Define `SaleItem` (`sku`, `qty`) and `Sale` (`items`, `payment_method`, `total`,
      `timestamp`, `sale_id`).
    - Validate: items count 1–100, each `qty` integer in `[1, 9999]`,
      `payment_method` in `{efectivo, tarjeta}`.
    - Compute `subtotal = round(unit_price * qty, 2)` and
      `total = sum(subtotals)` in `[0.01, 999999999.99]`, using `Decimal`.
    - _Requirements: 2.2, 2.3, 2.7, 2.8_

  - [ ]* 2.5 Write property test: sale total equals sum of rounded subtotals
    - **Property 5: Sale total equals the sum of rounded subtotals**
    - **Validates: Requirements 2.2**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 5`.

  - [ ]* 2.6 Write unit tests for model validation edge cases
    - Boundary values for price/stock/name/sku length and quantity bounds.
    - Empty items list rejected.
    - _Requirements: 1.3, 1.4, 2.6, 2.7, 2.8_

- [ ] 3. Checkpoint - domain models and validation
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement the repository layer and transactional fake
  - [ ] 4.1 Define the repository interface and single-table key design
    - Define a `PosRepository` protocol with: `get_product`, `put_product`
      (condition `attribute_not_exists(PK)`), `list_products`, `update_product`
      (condition `attribute_exists(PK)`), `commit_sale_transaction(actions)`
      (`TransactWriteItems`), and `query_sales_by_date`.
    - Encode key design: Product `PK=SK=PRODUCT#<sku>`; Sale `PK=SALE#<date>`,
      `SK=SALE#<ts>#<saleId>`; `Decimal`↔DynamoDB `Number` conversion helpers.
    - _Requirements: 1.1, 1.5, 1.7, 2.1, 4.1_

  - [ ] 4.2 Implement the in-memory transactional fake repository
    - Implement `TransactWriteItems` semantics: evaluate every action's condition first,
      then apply all writes atomically, or reject the whole batch (all-or-nothing).
    - On rejection, surface per-action `ConditionalCheckFailed` reasons so services can map
      offending SKUs; support an injectable non-condition failure (for Requirement 3.5).
    - Implement `attribute_not_exists`/`attribute_exists` conditions and
      `stock >= :qty` guarded decrements.
    - _Requirements: 3.2, 3.3, 3.4, 3.5_

  - [ ]* 4.3 Write unit tests for the transactional fake
    - Verify all-or-nothing: a failing condition in any action leaves all items unchanged.
    - Verify condition-failure reasons list the right keys; verify injected non-condition
      failure path.
    - _Requirements: 3.2, 3.4, 3.5_

  - [ ] 4.4 Implement the DynamoDB-backed repository (boto3)
    - Implement `PosRepository` against DynamoDB using `GetItem`, `PutItem`, `Scan`
      (filter `entity="PRODUCT"`), `UpdateItem`, `TransactWriteItems`, and `Query` on
      `PK=SALE#<date>`; read table name/region from environment variables (no secrets).
    - Parse `TransactionCanceledException.CancellationReasons` into offending SKUs vs.
      other failures.
    - _Requirements: 1.1, 1.5, 1.7, 2.1, 3.3, 3.5, 4.1_

- [ ] 5. Implement `Catalog_Service`
  - [ ] 5.1 Implement create, list, and update product operations
    - `create_product`: validate then `put_product` with duplicate-SKU rejection
      (leave existing unchanged).
    - `list_products`: return all products; empty catalog returns `[]`.
    - `update_product`: validate subset `{name, price, stock}`, require existing SKU,
      preserve previous values on invalid/missing update.
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 1.7, 1.8, 1.9_

  - [ ]* 5.2 Write property test: invalid create persists nothing (catalog-state half)
    - **Property 2: Invalid create is rejected and persists nothing**
    - **Validates: Requirements 1.2, 1.3, 1.4**
    - Assert catalog unchanged after rejection (duplicate SKU included).
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 2`.

  - [ ]* 5.3 Write property test: list returns exactly the created products
    - **Property 3: List returns exactly the created products**
    - **Validates: Requirements 1.5**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 3`.

  - [ ]* 5.4 Write property test: update preserves untouched fields; invalid/missing rejected
    - **Property 4: Update preserves untouched fields; invalid or missing update is rejected and preserves state**
    - **Validates: Requirements 1.7, 1.8, 1.9**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 4`.

  - [ ]* 5.5 Write unit test: empty catalog list returns []
    - _Requirements: 1.6_

- [ ] 6. Implement `Inventory_Service` and `Sales_Service` (atomic stock discount — core)
  - [ ] 6.1 Implement `Inventory_Service.build_sale_transaction`
    - Build one `Update` action per distinct product decrementing `stock` by its quantity,
      guarded by `attribute_exists(PK) AND stock >= :qty`, plus one `Put` for the sale item
      guarded by `attribute_not_exists(SK)`.
    - _Requirements: 3.1, 3.2_

  - [ ] 6.2 Implement `Inventory_Service.commit_sale` and `InsufficientStock`
    - Execute the transaction via the repository; on condition failure raise
      `InsufficientStock` listing exactly the offending SKUs; on other transactional
      failure raise `TransactionFailed`. No partial writes in any case.
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7_

  - [ ] 6.3 Implement `Sales_Service.register_sale` wiring validation + atomic commit
    - Validate the sale, look up products, compute total, assign a unique `sale_id` and
      registration timestamp (UTC), then commit atomically via `Inventory_Service`.
    - Reject non-existent SKU, empty items, invalid quantity, invalid payment method
      before any write; map `InsufficientStock`/`TransactionFailed` to error envelopes.
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.3, 3.5, 3.7_

  - [ ]* 6.4 Write property test: sale round-trips its fields with a unique id
    - **Property 6: Registered sale round-trips its fields with a unique id**
    - **Validates: Requirements 2.1, 2.3**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 6`.

  - [ ]* 6.5 Write property test: invalid sale is rejected and persists nothing
    - **Property 7: Invalid sale is rejected and persists nothing**
    - **Validates: Requirements 2.5, 2.7, 2.8**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 7`.

  - [ ]* 6.6 Write property test: sufficient stock decrements each product by its quantity
    - **Property 8: Sufficient stock decrements each product by its quantity**
    - **Validates: Requirements 3.1**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 8`.

  - [ ]* 6.7 Write property test: sale registration is all-or-nothing
    - **Property 9: Sale registration is all-or-nothing**
    - **Validates: Requirements 3.2, 3.4, 3.7**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 9`.

  - [ ]* 6.8 Write property test: insufficient stock rejects the sale and reports SKUs
    - **Property 10: Insufficient stock rejects the whole sale and reports offending SKUs**
    - **Validates: Requirements 3.3**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 10`.

  - [ ]* 6.9 Write property test: concurrent sales never oversell a product
    - **Property 11: Concurrent sales never oversell a product**
    - **Validates: Requirements 3.6, 3.7**
    - Apply competing sales as serialized conditional transactions against the fake.
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 11`.

  - [ ]* 6.10 Write unit tests: timestamp window and non-stock transaction failure
    - Timestamp recorded within a reasonable window around "now" (Requirement 2.4).
    - Injected non-stock transaction failure reverts cleanly, returns `TRANSACTION_FAILED`,
      stock preserved (Requirement 3.5).
    - _Requirements: 2.4, 3.5_

- [ ] 7. Checkpoint - catalog, sales, inventory and their properties
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Implement `Report_Service`
  - [ ] 8.1 Implement daily report aggregation
    - Validate the date (calendar format; reject future dates); default to system current
      date when omitted.
    - Query sales by date, compute `sales_count`, `total`, and `by_payment_method`
      (only methods with at least one sale); no sales → count 0, total `0.00`, empty map.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 8.2 Write property test: report aggregates count and total for its date
    - **Property 12: Daily report aggregates count and total for its date**
    - **Validates: Requirements 4.1**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 12`.

  - [ ]* 8.3 Write property test: breakdown partitions the total by payment method
    - **Property 13: Daily report breakdown partitions the total by payment method**
    - **Validates: Requirements 4.2**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 13`.

  - [ ]* 8.4 Write property test: invalid or future report dates are rejected
    - **Property 14: Invalid or future report dates are rejected and leave data unchanged**
    - **Validates: Requirements 4.5**
    - Hypothesis, min 100 iterations; `# Feature: pos-mvp, Property 14`.

  - [ ]* 8.5 Write unit tests: empty-date report and omitted-date default
    - No sales that date → count 0, total `0.00`, empty breakdown (Requirement 4.3).
    - Omitted date uses system current date (Requirement 4.4).
    - _Requirements: 4.3, 4.4_

- [ ] 9. Implement the FastAPI API layer and wire everything together
  - [ ] 9.1 Implement error handling and the JSON error envelope
    - Map each failure class to its HTTP status and `code` per the design error table
      (`VALIDATION_ERROR` 400, `DUPLICATE_SKU` 409, `PRODUCT_NOT_FOUND`/`UNKNOWN_SKU` 404,
      `INSUFFICIENT_STOCK` 409 with `skus`, `TRANSACTION_FAILED` 503, `INVALID_DATE` 400,
      `INTERNAL_ERROR` 500) via FastAPI exception handlers.
    - _Requirements: 1.2, 1.3, 1.4, 1.8, 1.9, 2.5, 2.6, 2.7, 2.8, 3.3, 3.5, 4.5_

  - [ ] 9.2 Implement catalog routes
    - `POST /products`, `GET /products`, `PUT /products/{sku}` delegating to
      `Catalog_Service`; dependency-inject the repository (DynamoDB or fake).
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 1.7, 1.8, 1.9_

  - [ ] 9.3 Implement sales and report routes and the ASGI/Lambda entrypoint
    - `POST /sales` → `Sales_Service.register_sale`;
      `GET /reports/daily?date=YYYY-MM-DD` → `Report_Service`.
    - Create the FastAPI app, wire all services, and expose the Mangum handler for Lambda.
    - _Requirements: 2.1, 3.3, 4.1, 4.4_

  - [ ]* 9.4 Write API integration tests against the FastAPI app with the fake repository
    - Catalog create/list/update happy paths and error envelopes; sale happy path and
      insufficient-stock 409 with `skus`; daily report happy path and invalid-date 400.
    - _Requirements: 1.1, 1.2, 1.8, 2.1, 2.5, 3.3, 4.1, 4.5_

- [ ] 10. Checkpoint - backend API complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 11. DynamoDB Local integration tests (AWS boundary)
  - [ ]* 11.1 Write integration test: atomic commit against DynamoDB Local
    - Real `TransactWriteItems` commits a sale and decrements stock atomically.
    - _Requirements: 3.1, 3.2_

  - [ ]* 11.2 Write integration test: real condition failure cancels the whole transaction
    - A real `stock >= qty` failure cancels the transaction and reports the SKU; stock
      preserved.
    - _Requirements: 3.3, 3.4_

  - [ ]* 11.3 Write integration test: concurrent transactions do not oversell
    - Two concurrent sale transactions for the same product: at most the set that fits the
      prior stock commits; the rest are rejected for insufficient stock.
    - _Requirements: 3.6, 3.7_

- [ ]* 12. Implement the React + Vite + TypeScript frontend
  - [ ]* 12.1 Scaffold the frontend and the typed API client
    - Create the Vite + React + TS app with a typed client for `/products`, `/sales`,
      `/reports/daily`; surface the API `code`/`message` with Spanish text.
    - _Requirements: 1.5, 2.1, 4.1_

  - [ ]* 12.2 Implement the catalog screen
    - Create/list/update products with large buttons and clear Spanish labels; show
      validation and duplicate-SKU errors.
    - _Requirements: 1.1, 1.2, 1.5, 1.7, 1.8, 1.9_

  - [ ]* 12.3 Implement the cart and checkout screen
    - Centralized cart state; confirm before registering a sale; show total, payment
      method, and the receipt; display insufficient-stock SKUs on 409.
    - _Requirements: 2.1, 2.2, 2.3, 3.3_

  - [ ]* 12.4 Implement the daily report screen
    - Date picker (default today), count, total, and breakdown by payment method; show
      invalid-date errors in Spanish.
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

  - [ ]* 12.5 Write frontend component tests
    - Cart totals, checkout confirmation flow, and error rendering.
    - _Requirements: 2.2, 3.3_

- [ ]* 13. Implement AWS SAM infrastructure
  - [ ]* 13.1 Author the SAM template
    - Define `AWS::Serverless::Api` (API Gateway), `AWS::Serverless::Function` (FastAPI via
      Mangum, Python 3.12), and `AWS::DynamoDB::Table` (`pos`, single table with `PK`/`SK`).
    - Inject table name/region via environment variables; grant a scoped IAM role limited to
      `GetItem`/`PutItem`/`Query`/`Scan`/`UpdateItem`/`TransactWriteItems` on the table;
      no secrets in the template.
    - _Requirements: 1.1, 2.1, 3.2, 4.1_

- [ ]* 14. Final checkpoint - full stack
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP. The required core
  is the backend business logic (tasks 1, 2.1, 2.4, 4.1, 4.2, 4.4, 5.1, 6.x implementation,
  8.1) and the API wiring (task 9). Frontend (task 12) and SAM infra (task 13) are optional,
  as are all test sub-tasks.
- Each task references specific requirements and, where applicable, the exact design property
  it implements for full traceability.
- All 14 correctness properties from `design.md` are implemented as Hypothesis
  property-based tests running a minimum of 100 iterations each, tagged with
  `# Feature: pos-mvp, Property {n}`.
- The atomic stock discount (Requirement 3 / Properties 8–11) is validated both against the
  in-memory transactional fake (tasks 6.6–6.9) and against DynamoDB Local (task 11).
- Property tests are placed close to the implementation they validate so errors are caught
  early; example and integration tests complement but do not replace them.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.4"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.5", "2.6", "4.1"] },
    { "id": 3, "tasks": ["4.2", "4.4"] },
    { "id": 4, "tasks": ["4.3", "5.1", "6.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5", "6.2"] },
    { "id": 6, "tasks": ["6.3", "8.1"] },
    { "id": 7, "tasks": ["6.4", "6.5", "6.6", "6.7", "6.8", "6.9", "6.10", "8.2", "8.3", "8.4", "8.5"] },
    { "id": 8, "tasks": ["9.1"] },
    { "id": 9, "tasks": ["9.2", "9.3"] },
    { "id": 10, "tasks": ["9.4", "11.1", "11.2", "11.3"] },
    { "id": 11, "tasks": ["12.1", "13.1"] },
    { "id": 12, "tasks": ["12.2", "12.3", "12.4"] },
    { "id": 13, "tasks": ["12.5"] }
  ]
}
```
