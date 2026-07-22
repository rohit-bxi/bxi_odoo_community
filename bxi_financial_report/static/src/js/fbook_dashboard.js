/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class FbookDashboard extends Component {
    static template = "bxi_financial_report.FbookTemplate";

    setup() {
        this.orm = useService("orm");

        const ctx = this.props.action.context || {};

        this.company_ids = ctx.company_ids || [];
        this.company_name = ctx.company_names || "";

        this.start_financial_year = ctx.start_financial_year || "";
        this.currency_id = ctx.currency_id || false;
        this.currency_symbol = ctx.currency_symbol || "";

        this.state = useState({
            report_data: {
                company_name: "",
                currency_symbol: "",
                year1_label: "",
                year2_label: "",
                data: {
                    y1: {
                        q1: {}, q2: {}, q3: {}, q4: {}, total: {}
                    },
                    y2: {
                        q1: {}, q2: {}, q3: {}, q4: {}, total: {}
                    }
                }
            },
            loaded: false,
        });

        onWillStart(async () => {
            if (!this.state.loaded) {
                await this.loadData();
                this.state.loaded = true;
            }
        });
    }

    async loadData() {
        const result = await this.orm.call(
            "fbook.report.wizard",
            "get_report_data",
            [],
            {
                company_ids: this.company_ids,
                start_financial_year: this.start_financial_year,
                currency_id: this.currency_id,

            }
        );
        this.state.report_data = result;
    }

    exportToExcel() {
        const container = document.querySelector(".fbook-dashboard-container");
        if (!container) return;

        const style = container.querySelector("style") ? container.querySelector("style").outerHTML : "";
        const tables = container.querySelectorAll("table");
        let tablesHtml = "";
        tables.forEach(table => {
            tablesHtml += table.outerHTML + "<br/><br/>";
        });
        
        const html = `<html><head><meta charset="utf-8"/>${style}</head><body>${tablesHtml}</body></html>`;

        const blob = new Blob(['\ufeff' + html], {
            type: 'application/vnd.ms-excel;charset=utf-8'
        });

        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `Fbook_Report_${this.company_name || 'Report'}_${this.start_financial_year || ''}.xls`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    /**
     * Format a numeric amount with locale thousand separators and 2 decimal places.
     * e.g. 296237.83 → "2,96,237.83"  (uses en-IN locale for Indian comma style)
     * Non-numeric / falsy values render as "0.00".
     */
    formatAmt(val) {
        const num = parseFloat(val);
        if (isNaN(num)) return "0.00";
        return num.toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    /**
     * Format a percentage value with 2 decimal places.
     * e.g. 45.678 → "45.68 %"
     */
    formatPct(val) {
        const num = parseFloat(val);
        if (isNaN(num)) return "0.00 %";
        return num.toFixed(2) + " %";
    }

}


registry.category("actions").add("bxi_fbook_report_dashboard", FbookDashboard);
