# -*- coding: utf-8 -*-

from odoo import models
import logging

_logger = logging.getLogger(__name__)


class SaleWorkflowProcess(models.Model):
    _inherit = 'sale.workflow.process.ept'

    def shipped_order_workflow_ept(self, orders):
        magento_orders = orders.filtered(lambda o: o.magento_instance_id)
        if magento_orders:
            _logger.warning(
                "Magento orders skipped from shipped workflow: %s",
                magento_orders.mapped('name')
            )

        non_magento_orders = orders.filtered(lambda o: not o.magento_instance_id)
        if not non_magento_orders:
            return True

        return super().shipped_order_workflow_ept(non_magento_orders)

    def auto_workflow_process_ept(self, auto_workflow_process_id=False, order_ids=[]):
        return super().auto_workflow_process_ept(
            auto_workflow_process_id=auto_workflow_process_id,
            order_ids=order_ids
        )
