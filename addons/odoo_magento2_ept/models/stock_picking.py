# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for Export shipment information.
"""
import logging
from odoo import models, fields, _
from odoo.exceptions import UserError
from .api_request import req

_logger = logging.getLogger("MagentoEPT")


class StockPicking(models.Model):
    """
    Describes methods for Export shipment information.
    """
    _inherit = 'stock.picking'
    _description = 'Stock Picking'

    is_magento_picking = fields.Boolean(string='Magento Picking?',
                                        help="If checked, It is Magento Picking")
    related_backorder_ids = fields.One2many(comodel_name='stock.picking',
                                            inverse_name='backorder_id',
                                            string="Related backorders",
                                            help="This field relocates related backorders")
    magento_website_id = fields.Many2one(compute="_compute_set_magento_info",
                                         comodel_name="magento.website",
                                         readonly=True,
                                         string="Website",
                                         help="Magento Websites")
    storeview_id = fields.Many2one(compute="_compute_set_magento_info",
                                   comodel_name="magento.storeview",
                                   readonly=True,
                                   string="Storeview",
                                   help="Magento Store Views")
    is_exported_to_magento = fields.Boolean(string="Exported to Magento?",
                                            help="If checked, Picking is exported to Magento")
    magento_instance_id = fields.Many2one(comodel_name='magento.instance',
                                          string='Magento Instance',
                                          help="This field relocates magento instance")
    magento_shipping_id = fields.Char(string="Magento Shipping Ids", help="Magento Shipping Ids")
    max_no_of_attempts = fields.Integer(string='Max NO. of attempts', default=0)
    magento_message = fields.Char(string="Picking Message")
    magento_inventory_source = fields.Many2one(comodel_name='magento.inventory.locations',
                                               string='Magento Inventory Sources',
                                               domain="[('magento_instance_id', '=', magento_instance_id)]")
    is_msi_enabled = fields.Boolean(related='magento_instance_id.is_multi_warehouse_in_magento')
    is_shipment_exportable = fields.Boolean(string="Is Shipment exportable",
                                            compute='_compute_shipment_exportable',
                                            store=False)

    def _compute_shipment_exportable(self):
        """
        set is_shipment_exportable true or false based on some condition
        :return:
        """
        location_obj = self.env["stock.location"]
        customer_locations = location_obj.search([("usage", "=", "customer")])
        if (self.location_dest_id.id in customer_locations.ids) and self.sale_id:
            self.is_shipment_exportable = True
        else:
            self.is_shipment_exportable = False

    def _compute_set_magento_info(self):
        """
        Computes Magento Information
        :return:
        """
        for record in self:
            if record.sale_id.magento_order_id:
                record.magento_website_id = record.sale_id.magento_website_id
                record.storeview_id = record.sale_id.store_id

    def get_export_ship_values(self, raise_error):
        """
        export shipment values create with item details.
        param: wizard - open this values export shipment (t/f).
        return : export shipment dict.
        """
        if self.carrier_id and not self.carrier_id.magento_carrier_code and not raise_error:
            message = "You are trying to Export Shipment Information" \
                      "\nBut Still, you didn't set the Magento " \
                      "Carrier Code for '{}' Delivery Method".format(self.carrier_id.name)
            if self.env.context.get('auto_export', False):
                log_line = self.env['common.log.lines.ept']
                log_line.create_common_log_line_ept(message=message, module='magento_ept', magento_instance_id=self.magento_instance_id.id,
                                                    operation_type='export', model_name='stock.picking')
                return False
            else:
                raise UserError(message)
        items = self.__prepare_export_shipment_items()
        tracks = self.get_magento_tracking_number()
        values = {
            "items": items,
            "tracks": tracks or []
        }
        if self.is_msi_enabled:
            magento_inventory_source = self.magento_inventory_source
            if not magento_inventory_source:
                inventory_loc_source = self.env['magento.inventory.locations'].search([
                    ('ship_from_location', '=', self.location_id.id),
                    ('magento_instance_id', '=', self.magento_instance_id.id)], order='id', limit=1)
                if inventory_loc_source:
                    magento_inventory_source = inventory_loc_source

            if magento_inventory_source:
                values.update({
                    "arguments": {
                        "extension_attributes": {
                            "source_code": magento_inventory_source.magento_location_code
                        }
                    }
                })
        return values

    def __prepare_export_shipment_items(self):
        """
        This method are used to prepare shipment items values.
        :return: list(dict(orderItemId, qty))
        """
        items = []
        for move in self.move_ids:
            item_id = move.sale_line_id.magento_sale_order_line_ref
            if move.sale_line_id and item_id:
                # order_item_id = move.sale_line_id.magento_sale_order_line_ref
                # only ship those qty with is done in picking. Not for whole order qty done
                items.append({
                    'orderItemId': item_id,
                    'qty': move.product_qty
                })
        return items

    def magento_send_shipment(self, raise_error=False):
        """
        This method are used to send the shipment to Magento. This is an base method and it calls
        from wizard, manual operation as well as cronjob.
        :param raise_error: If calls from manual operation then raise_error=True
        :return: Always True
        """
        for picking in self:
            values = picking.get_export_ship_values(raise_error=raise_error)
            if not values:
                return False
            instance = picking.magento_instance_id
            try:
                api_url = f'/V1/order/{picking.sale_id.magento_order_id}/ship/'
                response = req(instance, api_url, 'POST', values)
            except Exception as error:
                _logger.error(error)
                return picking._handle_magento_shipment_exception(instance, picking)
            if response:
                picking.write({
                    'magento_shipping_id': int(response),
                    'is_exported_to_magento': True
                })
        return True

    def _handle_magento_shipment_exception(self, instance, picking):
        """
        This method used to handle shipment response. Based on the response we will update the
        attempts and shipment id in picking record.
        :param instance: magento.instance object
        :param picking: stock.picking object
        :return: Always False due to this method calls from exception
        """
        log_line = self.env['common.log.lines.ept']
        order_name = picking.sale_id.name
        if picking.max_no_of_attempts == 2:
            note = f"""
            Attention {self.name} Export Shipment is processed 3 times and it failed. \n
            You need to process it manually.
            """
            self.env['magento.instance'].create_activity(model_name=self._name,
                                                         res_id=picking.id,
                                                         message=note,
                                                         summary=picking.name,
                                                         instance=instance)
        picking.write({
            "max_no_of_attempts": picking.max_no_of_attempts + 1,
            "magento_message": _(
                "The request could not be satisfied while export this Shipment."
                "\nPlease check Process log line")
        })
        message = _("The request could not be satisfied and shipment couldn't be "
                    "created in Magento for "
                    "Sale Order : {} & Picking : {} due to any of the following reasons.\n"
                    "1. A picking can't be created when an order has a status of "
                    "'On Hold/Canceled/Closed'\n"
                    "2. A picking can't be created without products. "
                    "Add products and try again.\n"
                    "3. The shipment information has not been exported due "
                    "to either missing carrier or"
                    " tracking number details.\n"
                    "4. In case you are using Magento multi-inventory sources, "
                    "ensure that you have selected the appropriate warehouse location for "
                    "the shipment in Odoo. "
                    "The warehouse location must be listed as one of the inventory sources "
                    "set up in Magento for the product. "
                    "Please go to Magento2 Odoo Connector > Configuration > "
                    "Magento Inventory location > Select Magento location name > "
                    "set Export Shipment location\n"
                    "The order does not allow an shipment to be created"). \
            format(order_name, picking.name)
        log_line.create_common_log_line_ept(message=message, module='magento_ept', order_ref=order_name,
                                            operation_type='import', model_name=self._name,
                                            magento_instance_id=self.magento_instance_id.id)
        return False

    def search_magento_pickings(self, instance):
        """
        This method are used to search the picking which are exportable. We only consider the
        OUTGOING pickings to be exported and if it already attempted more than 3 times then we
        will not export it again when cronjob runs.
        :param instance: magento.instance object
        :return: stock.picking records
        """
        location_obj = self.env["stock.location"]
        customer_locations = location_obj.search([("usage", "=", "customer")])
        return self.search([
            ('is_exported_to_magento', '=', False),
            ('state', 'in', ['done']),
            ('magento_instance_id', '=', instance.id),
            ('max_no_of_attempts', '<', 3),
            ("location_dest_id", "in", customer_locations.ids)
        ])

    def get_magento_tracking_number(self):
        """
        Add new Tracking Number for Picking.
        :return: list(tracking)
        """
        tracks = []
        carrier_code = self.carrier_id.magento_carrier_code
        title = self.carrier_id.magento_carrier.magento_carrier_title
        # for package in self.package_ids:
        for package in self.move_line_ids.result_package_id:
            tracks.append({
                'carrierCode': carrier_code,
                'title': title,
                'trackNumber': package.tracking_no or self.carrier_tracking_ref
            })
        if not tracks and self.carrier_tracking_ref:
            tracks.append({
                'carrierCode': carrier_code,
                'title': title,
                'trackNumber': self.carrier_tracking_ref
            })
        return tracks

    def export_magento_shipment(self):
        """
        This method calls from manual operation button provided in stock.picking.
        :return:
        """
        return self.magento_send_shipment(raise_error=True)
