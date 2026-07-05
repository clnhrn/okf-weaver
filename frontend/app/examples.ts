export const EXAMPLE_SQL = `CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(120),
    tier VARCHAR(20),
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    status VARCHAR(20),
    total NUMERIC(12, 2),
    currency CHAR(3),
    placed_at TIMESTAMP NOT NULL
);
`;

export const EXAMPLE_MANIFEST = `{
  "nodes": {
    "model.shop.dim_customers": {
      "resource_type": "model",
      "name": "dim_customers",
      "description": "One row per customer with lifetime attributes.",
      "columns": {
        "customer_id": { "name": "customer_id", "data_type": "integer", "description": "Surrogate key for the customer." },
        "email": { "name": "email", "data_type": "varchar", "description": "Primary contact email." },
        "lifetime_value": { "name": "lifetime_value", "data_type": "numeric", "description": "" }
      }
    },
    "model.shop.fct_orders": {
      "resource_type": "model",
      "name": "fct_orders",
      "description": "One row per placed order.",
      "columns": {
        "order_id": { "name": "order_id", "data_type": "integer", "description": "Order surrogate key." },
        "status": { "name": "status", "data_type": "varchar", "description": "" },
        "amount": { "name": "amount", "data_type": "numeric", "description": "" }
      }
    }
  }
}
`;
