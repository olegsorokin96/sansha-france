# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods to store Customer Data queue line
"""
import json
from odoo import models, fields


class MagentoCustomerQueueLineEpt(models.Model):
    """
    Describes Customer Data Queue Line
    """
    _name = "magento.customer.data.queue.line.ept"
    _description = "Magento Customer Data Queue Line EPT"
    _rec_name = "magento_id"

    queue_id = fields.Many2one(comodel_name='magento.customer.data.queue.ept', ondelete="cascade")
    instance_id = fields.Many2one(comodel_name='magento.instance',
                                  string='Magento Instance',
                                  help="Customer imported from this Magento Instance.")
    state = fields.Selection([("draft", "Draft"), ("failed", "Failed"),
                              ("done", "Done"), ("cancel", "Cancelled")], default="draft",
                             copy=False)
    magento_id = fields.Char(string="Customer ID", help="Id of imported customer.", copy=False)
    partner_id = fields.Many2one(comodel_name="res.partner", copy=False,
                                 help="Customer created in Odoo.")
    data = fields.Text(string="Data", copy=False,
                       help="Data imported from Magento of current customer.")
    processed_at = fields.Datetime(string="Process Time", copy=False,
                                   help="Shows Date and Time, When the data is processed")
    log_lines_ids = fields.One2many("common.log.lines.ept", "magento_customer_data_queue_line_id",
                                    help="Log lines created against which line.")

    def create_queue_line(self, instance, customer, queue):
        self.create({
            'magento_id': customer.get('id'),
            'instance_id': instance.id,
            'data': json.dumps(customer),
            'queue_id': queue.id,
            'state': 'draft',
        })
        return True

    def auto_process_customer_queues(self):
        query = """ SELECT queue_id FROM magento_customer_data_queue_line_ept WHERE state = 'draft'
                    GROUP BY queue_id, create_date
                    ORDER BY create_date ASC
                """
        self.env.cr.execute(query)
        queue_ids = [queue.get('queue_id') for queue in self.env.cr.dictfetchall()]
        queues = self.env[self.queue_id._name].browse(queue_ids)
        queues.filtered(lambda q: not q.is_action_require)
        queues.process_customer_queues()
        return True

    def process_queue_line(self):
        customer = self.env['magento.res.partner.ept']
        for line in self:
            customer = customer.create_magento_customer(line)
            line.write({'state': 'done'})
        return True
