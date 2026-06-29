/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class PLDashboard extends Component {
    static template = "bxi_accounting_report.PLTemplate";

    setup() {
        this.orm = useService("orm");

        const ctx = this.props.action.context || {};

        this.financial_year = ctx.financial_year || false;
        this.company_ids = ctx.company_ids || [];
        this.currency_id = ctx.currency_id || false;

        this.state = useState({
            customers: [],
            expenses: {},
            quarters: [],
            currency: {
                name: "USD",
                symbol: "$",
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
            "custom.pl.report",
            "get_filtered_data",
            [],
            {
                financial_year: this.financial_year,
                company_ids: this.company_ids,
                currency_id: this.currency_id, 
            }
        );
        this.state.customers = result.customers || [];
        this.state.expenses = result.expenses || {};
        this.state.quarters = result.quarters || ["q1", "q2", "q3", "q4"];

        if (result.currency) {
            this.state.currency = result.currency;
        }
    }

    getQuarterLabel(q) {
        const fy = this.financial_year;

        if (!fy) return q.toUpperCase();

        const start = parseInt(fy);
        const end = start + 1;

        return `${q.toUpperCase()} FY${start}-${end}`;
    }
}

registry.category("actions").add("custom_pl_dashboard", PLDashboard);