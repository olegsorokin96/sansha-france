# -*- coding: utf-8 -*-

import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class OrderQueueLine(models.Model):
    _name = 'order.queue.line'
    _description = 'Magento Order Queue Line'

    queue_id = fields.Many2one('order.queue', string='Queue', ondelete='cascade')
    magento_id = fields.Char('Magento Order ID')
    data = fields.Text('Magento Order Data')
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        default='draft'
    )
    error_message = fields.Text('Error Message')

    def process_order_queue_line(self, line, log_line):
        """
        Process single Magento order queue line
        """

        try:
            # ---------------------------------------------------------
            # Load raw Magento order JSON
            # ---------------------------------------------------------
            item = json.loads(line.data)

            # ---------------------------------------------------------
            # FIX: ENSURE ITEM PRICE EXISTS (Magento Admin "Price")
            # Magento REST:
            # - price        → unit price excl tax (what we need)
            # - base_price   → fallback
            # ---------------------------------------------------------
            for order_line in item.get('items', []):
                price = order_line.get('price')
                if price in (None, 0, '0', '0.0'):
                    order_line['price'] = order_line.get('base_price', 0.0)

            # ---------------------------------------------------------
            # Continue normal flow (DO NOT TOUCH)
            # ---------------------------------------------------------
            self.env['sale.order'].with_context(
                magento_order_data=item,
                queue_line_id=line.id
            ).create_or_update_magento_order(item, log_line)

            line.state = 'done'
            return True

        except Exception as e:
            line.state = 'error'
            line.error_message = str(e)
            raise
