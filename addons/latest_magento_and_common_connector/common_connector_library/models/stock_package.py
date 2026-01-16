# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
from odoo import models, fields


class StockPackage(models.Model):
    _inherit = 'stock.package'

    tracking_no = fields.Char("Additional Reference", help="This field is used for storing the tracking number.")
