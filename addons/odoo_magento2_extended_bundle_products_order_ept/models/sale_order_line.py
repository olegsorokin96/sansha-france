# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""For Odoo Magento2 Connector Module"""
from odoo import models, fields, api, _
from odoo.addons.odoo_magento2_ept.models import api_request
from odoo.addons.odoo_magento2_ept.python_library.php import Php as php


class SaleOrderLine(models.Model):
    """
        Describes Sale order line
    """
    _inherit = 'sale.order.line'

    magento_bom_id = fields.Many2one(comodel_name='mrp.bom', string="Bill Of Material Id",
                                     help="Use for specific Magento order, to identify the BOM "
                                          "product")

    def create_order_line(self, item, instance, log_line, line_id):
        order_lines = item.get('items')
        bundle_ids = []
        rounding = bool(instance.magento_tax_rounding_method == 'round_per_line')
        for line in order_lines:
            bom_id = self.env['mrp.bom']
            if line.get('product_type') in ['configurable']:
                continue
            elif line.get('product_type') == 'bundle' and line.get('item_id') not in bundle_ids:
                bundle_ids.append(line.get('item_id'))
                tax_items = [item.get('item_id') for item in item.get('items') if
                             item.get('parent_item_id') == line.get('item_id')]
                item.update(
                    {f'order_tax_{line.get("item_id")}': item.get(f'order_tax_{tax_items[0]}')})
                tax_method = item.get('website').tax_calculation_method
                queue_line = self.env['magento.order.data.queue.line.ept'].browse(line_id)
                is_processed, bom_id = self.__create_bundle_line(item=line, tax=tax_method,
                                                                 order=item.get('sale_order_id'),
                                                                 items=order_lines, log_line=log_line,
                                                                 queue_line=queue_line.id)
                if not is_processed:
                    return False
            if bundle_ids and line.get('parent_item_id') in bundle_ids:
                continue
            product = line.get('line_product')
            price = self.__find_order_item_price(item, line, instance)
            customer_option = self.__get_custom_option(item, line)
            if bom_id:
                product = bom_id.product_id
            line_vals = self.with_context(custom_options=customer_option).prepare_order_line_vals(
                item, line, product, price, instance)
            if bom_id:
                line_vals.update({'magento_bom_id': bom_id.id})
            order_line = self.create(line_vals)
            order_line.with_context(round=rounding)._compute_amount()
            self.__create_line_desc_note(customer_option, item.get('sale_order_id'))
        return True

    def __create_bundle_line(self, **kwargs):
        """
        This method are used to create bundled product order line, it will call the method
        which will verify the ordered component. If the component is not found then creates a
        log. This method call the child methods based on the conditions to find the BOM product.
        :created_by: Mayur Jotaniya
        :create_date: 28.09.2021
        :task_id : 178160
        -----------------
        :param kwargs: dict(lines, item, order, log_line, tax, queue_line, items)
        :return: skip_order, order_lines
        """
        is_process = True
        item = kwargs.get('item')
        order = kwargs.get('order')
        log_line = kwargs.get('log_line')
        bom = self.env['mrp.bom']
        instance = order.magento_instance_id
        queue_line = self.env['magento.order.data.queue.line.ept']
        components = self._verify_component(item, kwargs.get('items'), instance)
        if bool(components.get('mismatch')):
            # If mismatch log found then order will be skipped.
            is_process = False
            message = "Component {} Not Found in Magento Layer!!".format(
                ",".join(components.get('mismatch')))
            if kwargs.get('queue_line'):
                queue_line = queue_line.browse(kwargs.get('queue_line'))
            log_line.create_common_log_line_ept(message=message, order_ref=order.magento_order_reference,
                                                magento_order_data_queue_line_id=queue_line.id,
                                                magento_instance_id=instance.id)
            return is_process, False
        product = self._find_product_at_magento_layer(instance, item)
        if not product:
            # If BOM product not found in magento layer then search it on odoo product.product model
            product = self._find_odoo_product(**kwargs)
            if not product:
                # We will skip the order and return, if we don't found BOM product at Odoo.
                return False
        if product:
            bom = self._find_bom_product(product, components.get('component'))
            # values = self.prepare_order_line_vals(item, product, price)
            # values.update({'magento_bom_id': bom.id})
            # self.create(values)
            # item_price = self.calculate_order_item_price(kwargs.get('tax'), item)
            # values = self.create_sale_order_line_vals(item, item_price, product,
            #                                           kwargs.get('order'))
            # If BOM product ordered then need to set the mrp.bom id in sale order line.
            # values.update({'magento_bom_id': bom.id})
            # self.create(values)
        return is_process, bom

    def _find_odoo_product(self, **kwargs):
        """
        This method will be used to find the BOM type product at odoo, If the product is not found
        then we will send the API request to Magento to get the SKU of product and based
        on that we will try to search the product in Magento layer. If the product found,
        then we will write the magento_product_id in Magento product. Otherwise we will create
        new odoo product. It was already verified that all the components are available in odoo.
        So, we creates new product with type (product=Stockable).
        :created_by: Mayur Jotaniya
        :create_date: 28.09.2021
        :task_id : 178160
        -----------------
        :param kwargs: dict(lines, item, order, log_line, tax, queue_line, items)
        :return: product.product
        """
        item = kwargs.get('item')
        order = kwargs.get('order')
        log_line = kwargs.get('log_line')
        instance = order.magento_instance_id
        product = self.env['product.product']
        default_code = item.get('sku')
        # If the product is not available in magento layer then search in the
        # Odoo Product.
        product = product.search([('default_code', '=', item.get('sku'))], limit=1)
        if not product:
            # Send API request and get the parent item's SKU from Magento.
            default_code = self._get_product_sku_by_id(instance, item.get('product_id'), **kwargs)
            m_product = self.env['magento.product.product']
            # Update magento product id in Magento product layer if the product found
            # using SKU
            m_product = m_product.search([('magento_sku', '=', default_code),
                                          ('magento_instance_id', '=', instance.id)],
                                         limit=1)
            if m_product:
                m_product.write({'magento_product_id': item.get('product_id')})
                product = m_product.odoo_product_id
        if default_code and not product:
            product = product.search([('default_code', '=', default_code)], limit=1)
            if not product:
                # Need to create new BOM product
                product = product.create({
                    'default_code': default_code,
                    'name': item.get('name'),
                    'type': 'product'
                })
                # Changes as on 28.12.2023 By Ketan Chauhan
                # Create images from magento store when bundle product creating in odoo product.product
                # Not images creating in magento layer, because of not creating a bundle product in layer
                if instance.allow_import_image_of_products:
                    # We will only create image in odoo product if customer has enabled the configuration from instance.
                    m_template_t = self.env['magento.product.template']
                    m_product_t = self.env['magento.product.product']
                    prod_ids = [item.get('product_id')]
                    if prod_ids:
                        p_items = m_product_t.get_products(instance, prod_ids, item)
                        for p_item in p_items:
                            images = m_template_t.get_bundle_product_images(instance, p_item,
                                                                            item.get('store_id'),
                                                                            kwargs.get('queue_line'),
                                                                            order.magento_order_reference)
                            for image in images:
                                types = image.get('types', list())
                                if 'image' in types and not product.image_1920:
                                    product.product_tmpl_id.write({'image_1920': image.get('image_binary')})

                                    c_images = self.env['common.product.image.ept'].search([
                                        ('template_id', '=', product.product_tmpl_id.id),
                                        ('product_id', '=', False)])
                                    c_images = c_images.filtered(lambda c_im: c_im.image == image.get('image_binary'))
                                    c_images.write({'product_id': product.id})
                                m_template_t._search_common_image(image,
                                                                  template_id=product.product_tmpl_id.id,
                                                                  variant_id=product.id)
                # Changes as on 28.12.2023 By Ketan Chauhan - END
                message = "New Product {} Created!!".format(default_code)
                queue_line_id = kwargs.get('queue_line')
                log_line.create_common_log_line_ept(message=message, order_ref=order.magento_order_reference,
                                                    magento_order_data_queue_line_id=queue_line_id,
                                                    magento_instance_id=instance.id)
        return product

    def _find_product_at_magento_layer(self, instance, item):
        """
        This method are used to find product at Magento Layer,
        It will search the product by SKU first. If not found then will search by the product_id
        If still not found then return the product.product object, If found then will get the odoo
        product_id reference from it and return.
        :created_by: Mayur Jotaniya
        :create_date: 28.09.2021
        :task_id : 178160
        -----------------
        :param instance: magento.instance object
        :param item: dict(ordered item)
        :return: product.product record/object
        """
        product = self.env['product.product']
        m_product = self.env['magento.product.product']
        # Search the bundle product by sku in in Magento layer
        m_product = m_product.search([('magento_sku', '=', item.get('sku')),
                                      ('magento_instance_id', '=', instance.id)], limit=1)
        if m_product and m_product.odoo_product_id:
            product = m_product.odoo_product_id
        else:
            # Search the product by magento_product_id
            m_product = m_product.search([('magento_product_id', '=', item.get('product_id')),
                                          ('magento_instance_id', '=', instance.id)], limit=1)
            if m_product and m_product.odoo_product_id:
                product = m_product.odoo_product_id
        return product

    @staticmethod
    def _get_product_sku_by_id(instance, product_id, **kwargs):
        """
        This staticmethod are used to send the API request using Magento API interface.
        This only calls if the product are not found in Magento layer as well as Odoo Layer
        and If customer has enabled the dynamic SKU enabled in Bundle product at Magento
        then we are sending the Bundle product's request to get the actual SKU. Later-on
        will be search that product by SKU.
        :created_by: Mayur Jotaniya
        :create_date: 28.09.2021
        :task_id : 178160
        -----------------
        :param instance: magento.instance object
        :param product_id: magento_product_id
        :return: sku
        """
        item = kwargs.get('item', dict())
        req_filter = {'entity_id': product_id}
        req_filter = api_request.create_search_criteria(req_filter)
        req_filter = php.http_build_query(req_filter)
        url = '/V1/products?{}fields=items[id,sku]'.format(req_filter)
        response = api_request.req(instance=instance, path=url)
        product = dict()
        if not response:
            message = "We are unable to get the Product response from Magento." \
                      "Product #{}, ID#{} might be deleted at Magento.".format(item.get('sku'),
                                                                               item.get(
                                                                                   'product_id'))
            queue_line_id = kwargs.get('queue_line')
            order = kwargs.get('order')
            log_line = kwargs.get('log_line')
            log_line.create_common_log_line_ept(message=message, order_ref=order.magento_order_reference,
                                                magento_order_data_queue_line_id=queue_line_id,
                                                magento_instance_id=instance.id)
        elif response.get('items'):
            product = response.get('items')[0]
        return product.get('sku', '')

    def _verify_component(self, item, items, instance):
        """
        This method are used to verify the bundle product's component in odoo. If all the component
        are found in odoo then it will return the component list otherwise it will return the
        mismatch list. We are assuming the all the component of bundle product are simple product
        of Magento then we are finding it on magento layer. If that product not found in Magento
        layer then we will find it on Odoo product.product. Otherwise it will considered mismatch.
        :created_by: Mayur Jotaniya
        :create_date: 28.09.2021
        :task_id : 178160
        -----------------
        :param item: dict(order_item)
        :param items: list(ordered items)
        :param instance: magento.instance object
        :return: dict(mismatch, component)
        """
        component, miss_component = list(), list()
        m_product = self.env['magento.product.product']
        product = self.env['product.product']
        for line in items:
            if line.get('product_type') in ['simple', 'virtual'] and item.get(
                    'item_id') == line.get('parent_item_id'):
                m_product = m_product.search([('magento_instance_id', '=', instance.id),
                                              ('magento_product_id', '=', line.get('product_id'))],
                                             limit=1)
                if m_product:
                    product = m_product.odoo_product_id
                else:
                    product = product.search([('default_code', '=', line.get('sku'))], limit=1)
                if product:
                    component.append({
                        'quantity': line.get('qty_ordered', 1) / item.get('qty_ordered', 1),
                        'sku': line.get('sku'),
                        'odoo_product_id': product.id,
                    })
                else:
                    miss_component.append(line.get('sku'))
        return {
            'component': component,
            'mismatch': miss_component
        }

    def _find_bom_product(self, product, component):
        """
        This method are used to find the mrp.bom product by ordered product. If the BOM product
        is already available then verify the component of that product, if all the components are
        matched then return that BOM otherwise call the method which will create new BOM with
        ordered component.
        :created_by: Mayur Jotaniya
        :create_date: 28.09.2021
        :task_id : 178160
        -----------------
        :param product: product.product object (BOM product)
        :param component: list(dict()) Ordered component
        :return: mrp.bom record Selected BOM
        """
        bom = self.env['mrp.bom']
        is_matched = list()
        selected_bom = self.env['mrp.bom']
        component_ids = [item.get('odoo_product_id') for item in component]
        bom_products = bom.search([('product_tmpl_id', '=', product.product_tmpl_id.id),
                                   ('type', '=', 'phantom'),
                                   ('company_id', '=', self.env.company.id)])
        # We will search the BOM product based on the priority. First we will search with
        # company if the BOM is available with that company then we will also map the component.
        bom_products += bom.search([('product_tmpl_id', '=', product.product_tmpl_id.id),
                                    ('type', '=', 'phantom')])
        if not bom_products:
            return self._create_new_bom_product(product, component)
        # Added filter to check whether BOM product have only those components which are
        # used in sale order.
        for bom_product in bom_products.filtered(
                lambda b: len(b.bom_line_ids) == len(component_ids)):
            for item in bom_product.bom_line_ids:
                if item.product_id.id in component_ids:
                    if float(item.product_qty) == float(
                            sum([c.get('quantity') for c in component if
                                 c.get('odoo_product_id') == item.product_id.id])):
                        is_matched.append(True)
                    else:
                        is_matched.append(False)
                else:
                    is_matched.append(False)
            if all(is_matched):
                selected_bom = bom_product
                break
            else:
                is_matched.clear()
        if not is_matched or not all(is_matched):
            selected_bom = self._create_new_bom_product(product, component)
        return selected_bom

    def _create_new_bom_product(self, product, components):
        """
        This method are used to create new mrp.bom based on the ordered product and add the
        component on it.
        :created_by: Mayur Jotaniya
        :create_date: 28.09.2021
        :task_id : 178160
        -----------------
        :param product: product.product object (BOM product)
        :param components: list(dict()) Ordered component
        :return: mrp.bom object
        """
        bom_line = self.env['mrp.bom.line']
        bom_product = self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'type': 'phantom',
            'product_id': product.id,
        })
        for component in components:
            bom_line.create({
                'product_id': component.get('odoo_product_id'),
                'product_qty': component.get('quantity'),
                'bom_id': bom_product.id
            })
        return bom_product
