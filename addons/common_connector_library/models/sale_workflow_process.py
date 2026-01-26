# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class SaleWorkflowProcess(models.Model):
    _name = "sale.workflow.process.ept"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "sale workflow process"

    @api.model
    def _default_journal(self):
        account_journal_obj = self.env['account.journal']
        company_id = self.env.context.get('company_id', self.env.company.id)
        domain = [('type', '=', "sale"), ('company_id', '=', company_id)]
        return account_journal_obj.search(domain, limit=1)

    name = fields.Char(size=64)
    validate_order = fields.Boolean(
        "Confirm Quotation",
        default=False,
        help="If it's checked, Order will be Validated.",
        tracking=True
    )
    create_invoice = fields.Boolean(
        'Create & Validate Invoice',
        default=False,
        help="If it's checked, Invoice for Order will be Created and Posted.",
        tracking=True
    )
    register_payment = fields.Boolean(
        default=False,
        help="If it's checked, Payment will be registered for Invoice.",
        tracking=True
    )
    invoice_date_is_order_date = fields.Boolean(
        'Force Accounting Date',
        help="If it is checked then, the account journal entry will be generated "
             "based on Order date and if unchecked then, based on Invoice Date",
        tracking=True
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain=[('type', 'in', ['cash', 'bank'])],
        tracking=True
    )
    sale_journal_id = fields.Many2one(
        'account.journal',
        string='Sales Journal',
        default=_default_journal,
        domain=[('type', '=', 'sale')],
        tracking=True
    )
    picking_policy = fields.Selection(
        [('direct', 'Deliver each product when available'),
         ('one', 'Deliver all products at once')],
        string='Shipping Policy',
        default="one",
        tracking=True
    )
    inbound_payment_method_id = fields.Many2one(
        'account.payment.method',
        string="Debit Method",
        domain=[('payment_type', '=', 'inbound')],
        tracking=True
    )

    @api.onchange("validate_order")
    def onchange_validate_order(self):
        for record in self:
            if not record.validate_order:
                record.create_invoice = False

    @api.onchange("create_invoice")
    def onchange_create_invoice(self):
        for record in self:
            if not record.create_invoice:
                record.register_payment = False

    @api.model
    def auto_workflow_process_ept(self, auto_workflow_process_id=False, order_ids=[]):
        sale_order_obj = self.env['sale.order']
        workflow_process_obj = self.env['sale.workflow.process.ept']

        if not auto_workflow_process_id:
            work_flow_process_records = workflow_process_obj.search([])
        else:
            work_flow_process_records = workflow_process_obj.browse(auto_workflow_process_id)

        if not order_ids:
            orders = sale_order_obj.search([
                ('auto_workflow_process_id', 'in', work_flow_process_records.ids),
                ('state', 'not in', ('done', 'cancel', 'sale')),
                ('invoice_status', '!=', 'invoiced')
            ])
        else:
            orders = sale_order_obj.search([
                ('auto_workflow_process_id', 'in', work_flow_process_records.ids),
                ('id', 'in', order_ids)
            ])

        orders.process_orders_and_invoices_ept()
        return True

    def shipped_order_workflow_ept(self, orders):
        """
        IMPORTANT CHANGE:
        Magento orders MUST ALWAYS remain quotations.
        """

        self.ensure_one()

        # 🔴 ЕСЛИ ЭТО MAGENTO-ЗАКАЗ — НИЧЕГО НЕ ДЕЛАЕМ
        magento_orders = orders.filtered(lambda o: o.magento_instance_id)
        if magento_orders:
            return True

        # 🟢 ОРИГИНАЛЬНАЯ ЛОГИКА ДЛЯ НЕ-MAGENTO
        stock_location_obj = self.env["stock.location"]
        product_product_obj = self.env["product.product"]
        mrp_module = product_product_obj.search_installed_module_ept('mrp')
        customer_location = stock_location_obj.search([("usage", "=", "customer")], limit=1)

        shipped_orders = orders.filtered(lambda x: x.order_line)
        for order in shipped_orders:
            order.state = 'sale'
            references = order.stock_reference_ids
            if not references:
                self.env['stock.reference'].create({
                    'name': order.name,
                    'sale_ids': [(4, order.id)],
                })
            order.auto_shipped_order_ept(customer_location, mrp_module)

        shipped_orders.validate_and_paid_invoices_ept(self)
        return True
