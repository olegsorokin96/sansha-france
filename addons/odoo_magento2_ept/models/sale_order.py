# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes fields and methods for create/ update sale order
AUTO WORKFLOW DISABLED:
Magento orders are always imported as Quotation (draft).
"""
import json
import pytz
import time
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .api_request import req
from dateutil import parser

utc = pytz.utc

MAGENTO_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
SALE_ORDER_LINE = 'sale.order.line'

import logging
_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_magento_order_status(self):
        for order in self:
            if order.magento_instance_id:
                pickings = order.picking_ids.filtered(lambda x: x.state != "cancel")
                stock_moves = order.order_line.move_ids.filtered(
                    lambda x: not x.picking_id and x.state == 'done')
                if pickings:
                    outgoing_picking = pickings.filtered(
                        lambda x: x.location_dest_id.usage == "customer")
                    if all(outgoing_picking.mapped("is_exported_to_magento")):
                        order.updated_in_magento = True
                        continue
                if stock_moves:
                    order.updated_in_magento = True
                    continue
                order.updated_in_magento = False
                continue
            order.updated_in_magento = False

    def _search_magento_order_ids(self, operator, value):
        if self:
            query = """select so.id from stock_picking sp
                        inner join sale_order so on so.procurement_group_id=sp.group_id
                        inner join stock_location on stock_location.id=sp.location_dest_id and stock_location.usage='customer'
                        where sp.is_exported_to_magento %s true and sp.state != 'cancel'
                        """
            if operator == '=':
                query += """union all
                        select so.id from sale_order as so
                        inner join sale_order_line as sl on sl.order_id = so.id
                        inner join stock_move as sm on sm.sale_line_id = sl.id
                        where sm.picking_id is NULL and sm.state = 'done' and so.magento_instance_id notnull"""
            self.env.cr.execute(query, (operator,))
        results = self.env.cr.fetchall()
        order_ids = list({r[0] for r in results})
        return [('id', 'in', order_ids)]

    magento_instance_id = fields.Many2one('magento.instance', string="Magento Instance", copy=False)
    magento_order_id = fields.Char(string="order Id", copy=False)
    magento_website_id = fields.Many2one("magento.website", string="Website")
    magento_order_reference = fields.Char(string="Orders Reference", copy=False)
    store_id = fields.Many2one('magento.storeview', string="Storeview")
    is_exported_to_magento_shipment_status = fields.Boolean(string="Is Order exported to Shipment Status")
    magento_payment_method_id = fields.Many2one('magento.payment.method', string="Payment Method")
    magento_shipping_method_id = fields.Many2one('magento.delivery.carrier', string="Magento Shipping Method")
    order_transaction_id = fields.Char(string="Magento Orders Transaction ID")
    updated_in_magento = fields.Boolean(
        string="Order fulfilled in magento",
        compute="_get_magento_order_status",
        search="_search_magento_order_ids",
        copy=False
    )

    _magento_sale_order_unique_constraint = models.Constraint(
        'unique(magento_order_id,magento_instance_id,magento_order_reference)',
        "Magento order must be unique"
    )

    def create_sale_order_ept(self, item, instance, log_line, line_id):
        is_processed = self._find_price_list(item, log_line, line_id, instance)
        order_line = self.env['sale.order.line']
        if is_processed:
            customers = self.__update_partner_dict(item, instance)
            data = self.env['magento.res.partner.ept'].create_magento_customer(customers, True)
            item.update(data)
            is_processed = self.__find_order_warehouse(item, log_line, line_id)
            if is_processed:
                is_processed = order_line.find_order_item(item, instance, log_line, line_id)
                if is_processed:
                    is_processed = self.__find_order_tax(item, instance, log_line, line_id)
                    if is_processed:
                        vals = self._prepare_order_dict(item, instance)
                        magento_order = self.create(vals)
                        item.update({'sale_order_id': magento_order})
                        order_line.create_order_line(item, instance, log_line, line_id)
                        self.__create_discount_order_line(item, instance)
                        self.__create_shipping_order_line(item, instance)
                        self.__process_order_workflow(item, log_line)
        return is_processed

    def __process_order_workflow(self, item, log_line):
        """
        AUTO WORKFLOW DISABLED:
        Always keep Magento orders as Quotation (draft).
        """
        _logger.info(
            "Magento order %s imported as Quotation only (auto workflow disabled)",
            item.get('increment_id')
        )
        return True
