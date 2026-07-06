--
-- Sample SQL Server schema in SSMS "Generate Scripts" style.
-- Uses [bracketed] identifiers, PRIMARY KEY CLUSTERED inside CREATE TABLE, FKs
-- as separate ALTER TABLE statements, and GO batch separators. Paste or upload
-- this into OKF Weaver to try it out.
--

SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

CREATE TABLE [dbo].[customers](
    [id] [int] IDENTITY(1,1) NOT NULL,
    [email] [nvarchar](255) NOT NULL,
    [full_name] [nvarchar](120) NOT NULL,
    [tier] [nvarchar](20) NULL,
    [is_active] [bit] NOT NULL,
    [created_at] [datetime2](7) NOT NULL,
 CONSTRAINT [PK_customers] PRIMARY KEY CLUSTERED ([id] ASC)
)
GO

CREATE TABLE [dbo].[products](
    [id] [int] IDENTITY(1,1) NOT NULL,
    [sku] [nvarchar](64) NOT NULL,
    [name] [nvarchar](200) NOT NULL,
    [unit_price] [decimal](12, 2) NOT NULL,
    [in_stock] [bit] NOT NULL,
 CONSTRAINT [PK_products] PRIMARY KEY CLUSTERED ([id] ASC)
)
GO

CREATE TABLE [dbo].[orders](
    [id] [int] IDENTITY(1,1) NOT NULL,
    [customer_id] [int] NOT NULL,
    [status] [nvarchar](20) NOT NULL,
    [total_amount] [decimal](12, 2) NOT NULL,
    [placed_at] [datetime2](7) NOT NULL,
 CONSTRAINT [PK_orders] PRIMARY KEY CLUSTERED ([id] ASC)
)
GO

CREATE TABLE [dbo].[order_items](
    [id] [int] IDENTITY(1,1) NOT NULL,
    [order_id] [int] NOT NULL,
    [product_id] [int] NOT NULL,
    [quantity] [int] NOT NULL,
    [unit_price] [decimal](12, 2) NOT NULL,
 CONSTRAINT [PK_order_items] PRIMARY KEY CLUSTERED ([id] ASC)
)
GO

ALTER TABLE [dbo].[orders] WITH CHECK ADD CONSTRAINT [FK_orders_customers] FOREIGN KEY([customer_id])
REFERENCES [dbo].[customers] ([id])
GO

ALTER TABLE [dbo].[order_items] WITH CHECK ADD CONSTRAINT [FK_order_items_orders] FOREIGN KEY([order_id])
REFERENCES [dbo].[orders] ([id])
GO

ALTER TABLE [dbo].[order_items] WITH CHECK ADD CONSTRAINT [FK_order_items_products] FOREIGN KEY([product_id])
REFERENCES [dbo].[products] ([id])
GO
