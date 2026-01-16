/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { SettingsFormCompiler } from "@web/webclient/settings_form_view/settings_form_compiler";
import { append, createElement } from "@web/core/utils/xml";
import { FormCompiler } from "@web/views/form/form_compiler";
import { getModifier } from "@web/views/view_compiler";

function compileSettingsPage(el, params) {
    const settingsPage = createElement("SettingsPage");
    settingsPage.setAttribute("slots", "{NoContentHelper:props.slots.NoContentHelper}");
    settingsPage.setAttribute("initialTab", "props.initialApp");
    settingsPage.setAttribute("t-slot-scope", "settings");

    //props
    const modules = [];

    for (const child of el.children) {
        if (child.nodeName === "div" && child.classList.value.includes("app_settings_block")) {
            params.module = {
                key: child.getAttribute("data-key"),
                string: child.getAttribute("string"),
                imgurl: getAppIconUrl(child.getAttribute("data-key")),
                isVisible: getModifier(child, "invisible"),
            };
            if (!child.classList.value.includes("o_not_app")) {
                modules.push(params.module);
                append(settingsPage, this.compileNode(child, params));
            }
        }
    }

    settingsPage.setAttribute("modules", JSON.stringify(modules));
    return settingsPage;
}

function getAppIconUrl(module) {
    if (module == 'odoo_magento2_ept_websites' || module == 'odoo_magento2_ept_storeviews') {
        return "/odoo_magento2_ept/static/description/icon.png";
    }
    else {
        return module === "general_settings" ? "/base/static/description/settings.png" : "/" + module + "/static/description/icon.png";
    }
}

patch(SettingsFormCompiler.prototype, "odoo_magento2_ept", {
    /**
     * @override
     */

    setup() {
        const res = this._super(...arguments);
        this.compilers.unshift(
            { selector: "div.settings", fn: compileSettingsPage },
        );
    }
});