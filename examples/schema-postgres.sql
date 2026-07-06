--
-- Sample PostgreSQL schema in `pg_dump --schema-only` style.
-- Primary and foreign keys arrive as separate ALTER TABLE statements, exactly
-- as pg_dump emits them. Paste or upload this into OKF Weaver to try it out.
--

SET statement_timeout = 0;
SET client_encoding = 'UTF8';
SET search_path = public;

CREATE TABLE public.customers (
    id integer NOT NULL,
    email character varying(255) NOT NULL,
    full_name character varying(120) NOT NULL,
    tier character varying(20),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.products (
    id integer NOT NULL,
    sku character varying(64) NOT NULL,
    name character varying(200) NOT NULL,
    unit_price numeric(12,2) NOT NULL,
    in_stock boolean DEFAULT true NOT NULL
);

CREATE TABLE public.orders (
    id integer NOT NULL,
    customer_id integer NOT NULL,
    status character varying(20) NOT NULL,
    total_amount numeric(12,2) NOT NULL,
    placed_at timestamp with time zone NOT NULL
);

CREATE TABLE public.order_items (
    id integer NOT NULL,
    order_id integer NOT NULL,
    product_id integer NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(12,2) NOT NULL
);

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id);

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id);

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);
