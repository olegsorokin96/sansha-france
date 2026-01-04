# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes new fields and methods for common log lines
"""
from odoo import models, fields


class CommonLogLineEpt(models.Model):
    """
    Describes common log book line
    """
    _inherit = "common.log.lines.ept"
    _rec_name = "common_log_rec_name"

    magento_instance_id = fields.Many2one(comodel_name='magento.instance', string='Instance',
                                          help="Magento Instance.")
    magento_order_data_queue_line_id = fields.Many2one(
        string="Magento Order Queue Line", comodel_name="magento.order.data.queue.line.ept")
    magento_import_product_queue_line_id = fields.Many2one(
        string="Magento Product Queue Line", comodel_name="sync.import.magento.product.queue.line")
    magento_customer_data_queue_line_id = fields.Many2one(
        string="Magento Customer Queue Line", comodel_name="magento.customer.data.queue.line.ept")
    magento_export_stock_queue_line_id = fields.Many2one(
        string="Magento Export Stock Queue Line", comodel_name="magento.export.stock.queue.line.ept")
    common_log_rec_name = fields.Char('Log Lines', compute="_compute_common_log_rec_name")

    def _compute_common_log_rec_name(self):
        for rec in self:
            rec.common_log_rec_name = rec.order_ref or rec.default_code or 'Log Record'
