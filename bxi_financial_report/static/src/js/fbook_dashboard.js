/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class FbookDashboard extends Component {
    static template = "bxi_financial_report.FbookTemplate";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

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
            show_all_vendors: false,
            expanded_rows: {},
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

    async exportToExcel() {
        try {
            const action = await this.orm.call(
                "fbook.report.wizard",
                "action_export_excel",
                [],
                {
                    company_ids: this.company_ids,
                    start_financial_year: this.start_financial_year,
                    currency_id: this.currency_id,
                }
            );

            if (action && action.url) {
                const a = document.createElement("a");
                a.href = action.url;
                if (action.name) {
                    a.download = action.name;
                }
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                return;
            } else if (action && this.action) {
                return this.action.doAction(action);
            }
        } catch (err) {
            console.error("Backend Excel export failed, falling back to client-side exporter:", err);
            this.exportToExcelFallback();
        }
    }

    exportToExcelFallback() {
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
        const compName = (this.state.report_data && this.state.report_data.company_name) || this.company_name || 'Report';
        a.download = `Fbook_Report_${compName}_${this.start_financial_year || ''}.xls`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    /**
     * Get company names formatted into lines of 2 to 3 companies per line.
     */
    get companyLines() {
        const data = this.state.report_data;
        if (data && data.company_lines && data.company_lines.length) {
            return data.company_lines;
        }
        if (data && data.companies && data.companies.length) {
            const chunkSize = data.companies.length === 4 ? 2 : 3;
            const lines = [];
            for (let i = 0; i < data.companies.length; i += chunkSize) {
                const chunk = data.companies.slice(i, i + chunkSize);
                lines.push(chunk.map(c => c.name).join(", "));
            }
            return lines;
        }
        const compStr = (data && (data.company_name_only || data.company_name)) || '';
        if (compStr.includes(",")) {
            const parts = compStr.split(",").map(s => s.trim()).filter(Boolean);
            const chunkSize = parts.length === 4 ? 2 : 3;
            const lines = [];
            for (let i = 0; i < parts.length; i += chunkSize) {
                lines.push(parts.slice(i, i + chunkSize).join(", "));
            }
            return lines;
        }
        return compStr ? [compStr] : [];
    }

    /**
     * Get vendor rows sorted descending by total billing value (highest billing first).
     */
    get sortedVendorRows() {
        const rows = (this.state.report_data && this.state.report_data.vendor_rows) || [];
        return [...rows].sort((a, b) => {
            const billedA = (parseFloat(a.y1_billed) || 0) + (parseFloat(a.y2_billed) || 0);
            const billedB = (parseFloat(b.y1_billed) || 0) + (parseFloat(b.y2_billed) || 0);
            if (billedB !== billedA) {
                return billedB - billedA;
            }
            const maxSingleA = Math.max(parseFloat(a.y1_billed) || 0, parseFloat(a.y2_billed) || 0);
            const maxSingleB = Math.max(parseFloat(b.y1_billed) || 0, parseFloat(b.y2_billed) || 0);
            if (maxSingleB !== maxSingleA) {
                return maxSingleB - maxSingleA;
            }
            return (a.vendor || "").localeCompare(b.vendor || "");
        });
    }

    /**
     * Get vendor rows to display: top 5 with maximum billing value by default, or all if toggled.
     */
    get displayedVendorRows() {
        const sorted = this.sortedVendorRows;
        if (this.state.show_all_vendors || sorted.length <= 5) {
            return sorted;
        }
        return sorted.slice(0, 5);
    }

    /**
     * Toggle between top 5 and all vendor rows.
     */
    toggleShowAllVendors() {
        this.state.show_all_vendors = !this.state.show_all_vendors;
    }

    /**
     * Toggle drill-down state for a specific tree row/key.
     */
    toggleDrill(key) {
        this.state.expanded_rows[key] = !this.state.expanded_rows[key];
    }

    /**
     * Check if a specific tree row/key is currently expanded.
     */
    isExpanded(key) {
        return !!this.state.expanded_rows[key];
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
        let num = parseFloat(val);
        if (isNaN(num)) return "0.00 %";
        if (num > 100) num = 100;
        return num.toFixed(2) + " %";
    }

}


registry.category("actions").add("bxi_fbook_report_dashboard", FbookDashboard);
