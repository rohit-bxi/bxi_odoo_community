/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { companyService } from "@web/webclient/company_service";

patch(companyService, {
    start(env, services) {
        const company = super.start(env, services);
        const originalSetCompanies = company.setCompanies.bind(company);

        function getGroupedSubCompanyIds(companyId) {
            const result = new Set();
            // 1. Check if target company has sub-companies directly listed in its grouped_company_ids
            const mainComp = company.availableCompanies[companyId];
            if (mainComp && Array.isArray(mainComp.grouped_company_ids)) {
                for (const gid of mainComp.grouped_company_ids) {
                    if (company.availableCompanies[gid]) {
                        result.add(gid);
                    }
                }
            }
            // 2. Also check any company in availableCompanies whose main_company_id === companyId
            for (const [idStr, c] of Object.entries(company.availableCompanies)) {
                if (c && c.main_company_id === companyId) {
                    const id = parseInt(idStr, 10);
                    if (company.availableCompanies[id]) {
                        result.add(id);
                    }
                }
            }
            return Array.from(result);
        }

        company.setCompanies = function (mode, ...companyIds) {
            if (mode === "toggle") {
                const [targetId] = companyIds;
                const isCurrentlyActive = company.activeCompanyIds.includes(targetId);
                const groupedIds = getGroupedSubCompanyIds(targetId);

                if (!isCurrentlyActive) {
                    // Activating targetId -> also activate all grouped sub-companies
                    const toAdd = [targetId, ...groupedIds].filter(
                        (id) => company.availableCompanies[id] && !company.activeCompanyIds.includes(id)
                    );
                    const newActive = Array.from(new Set([...company.activeCompanyIds, ...toAdd]));
                    return originalSetCompanies("set", ...newActive);
                } else {
                    // Deactivating targetId -> also deactivate all grouped sub-companies
                    const toRemove = new Set([targetId, ...groupedIds]);
                    const newActive = company.activeCompanyIds.filter((id) => !toRemove.has(id));
                    if (newActive.length === 0) {
                        return originalSetCompanies(mode, ...companyIds);
                    }
                    return originalSetCompanies("set", ...newActive);
                }
            } else if (mode === "set") {
                const finalIds = new Set();
                for (const id of companyIds) {
                    if (company.availableCompanies[id]) {
                        finalIds.add(id);
                        const groupedIds = getGroupedSubCompanyIds(id);
                        for (const gid of groupedIds) {
                            if (company.availableCompanies[gid]) {
                                finalIds.add(gid);
                            }
                        }
                    }
                }
                return originalSetCompanies("set", ...Array.from(finalIds));
            } else {
                return originalSetCompanies(mode, ...companyIds);
            }
        };

        return company;
    },
});
