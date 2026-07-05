CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(120),
    tier VARCHAR(20),
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    sku VARCHAR(40) NOT NULL,
    name VARCHAR(200) NOT NULL,
    list_price NUMERIC(12, 2),
    is_active BOOLEAN NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    status VARCHAR(20),
    total NUMERIC(12, 2),
    currency CHAR(3),
    placed_at TIMESTAMP NOT NULL
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(12, 2),
    discount NUMERIC(5, 2)
);
