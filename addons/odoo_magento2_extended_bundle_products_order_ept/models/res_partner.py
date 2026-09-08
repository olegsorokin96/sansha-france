# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for importing magento customers into Odoo.
"""
import json
import logging
from odoo import models, fields, api, _

MAGENTO_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
MAGENTO_RES_PARTNER_EPT = 'magento.res.partner.ept'
_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    pass