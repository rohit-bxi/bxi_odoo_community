/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CompanySelector } from "@web/webclient/switch_company_menu/switch_company_menu";
import { user } from "@web/core/user";

patch(CompanySelector.prototype, {
    _getBranches(companyId) {
        const branches = super._getBranches(companyId) || [];
        const result = new Set(branches);

        const comp = (user.allowedCompaniesWithAncestors || []).find((c) => c.id === companyId);
        if (comp && Array.isArray(comp.grouped_company_ids)) {
            for (const gid of comp.grouped_company_ids) {
                result.add(gid);
            }
        }

        for (const c of user.allowedCompaniesWithAncestors || []) {
            if (c && c.main_company_id === companyId) {
                result.add(c.id);
            }
        }

        return Array.from(result);
    },
});
