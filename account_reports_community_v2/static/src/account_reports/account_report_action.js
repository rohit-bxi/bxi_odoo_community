import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { download } from "@web/core/network/download";

export class AccountReportAction extends Component {
    static template = "account_reports_community_v2.AccountReportAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    // -- lifecycle / data loading ---------------------------------------------

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.reportId = this.props.action.context.report_id;
        this.focusAccountId = this.props.action.context.focus_account_id || null;
        this.focusPartnerId = this.props.action.context.focus_partner_id || null;
        this.searchDebounceTimer = null;

        this.state = useState({
            report: null,
            unfoldedLineIds: [],
            openMenuLineId: null,
            dateFrom: this.props.action.context.date_from || null,
            dateTo: this.props.action.context.date_to || null,
            search: "",
            journalIds: [],
            allEntries: false,
            availableJournals: [],
            journalMenuOpen: false,
            currencyId: null,
            availableCurrencies: [],
            currencyMenuOpen: false,
            comparisonEnabled: false,
            periodGranularity: null,
            presetMenuOpen: false,
            partnerIds: [],
            availablePartners: [],
            partnerMenuOpen: false,
            partnerFilterQuery: "",
            isLoading: false,
            loadingMoreLineId: null,
        });

        this.display = { controlPanel: {} };

        onWillStart(async () => {
            await Promise.all([this.loadReport(), this.loadJournals(), this.loadPartners(), this.loadCurrencies()]);
        });
    }

    async loadJournals() {
        this.state.availableJournals = await this.orm.call(
            "account.report",
            "action_get_available_journals",
            [[this.reportId]],
        );
    }

    async loadCurrencies() {
        this.state.availableCurrencies = await this.orm.call(
            "account.report",
            "action_get_available_currencies",
            [[this.reportId]],
        );
    }

    async loadPartners() {
        this.state.availablePartners = await this.orm.call(
            "account.report",
            "action_get_available_partners",
            [[this.reportId]],
        );
    }

    buildOptions() {
        return {
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
            currency_id: this.state.currencyId,
            unfolded_line_ids: [...this.state.unfoldedLineIds],
            focus_account_id: this.focusAccountId,
            focus_partner_id: this.focusPartnerId,
            search: this.state.search,
            journal_ids: this.state.journalIds.length ? [...this.state.journalIds] : null,
            partner_ids: this.state.partnerIds.length ? [...this.state.partnerIds] : null,
            all_entries: this.state.allEntries,
            comparison_periods: this.state.comparisonEnabled ? 1 : 0,
            period_granularity: this.state.periodGranularity,
        };
    }

    async toggleComparison() {
        this.state.comparisonEnabled = !this.state.comparisonEnabled;
        await this.loadReport();
    }

    async loadReport() {
        this.state.isLoading = true;
        try {
            this.state.report = await this.orm.call(
                "account.report",
                "action_get_report_data",
                [[this.reportId]],
                { options: this.buildOptions() },
            );
            // Seed the date filters from the server-resolved defaults on first
            // load (fiscal-year-to-date), so the inputs show real values, not blanks.
            if (!this.state.dateFrom) {
                this.state.dateFrom = this.state.report.options.date_from;
            }
            if (!this.state.dateTo) {
                this.state.dateTo = this.state.report.options.date_to;
            }
            if (!this.state.currencyId) {
                this.state.currencyId = this.state.report.options.currency_id;
            }
            // Mark every currently-unfolded row as fetched, so a later plain
            // fold/re-unfold (with no filter change) can skip the RPC entirely
            // and just toggle visibility of data we already have in memory.
            this.markFetched(this.state.report.lines || []);
        } finally {
            this.state.isLoading = false;
        }
    }

    /** PDF/XLSX export both hit a plain HTTP controller (not orm.call) since
     * the response is a binary file, not JSON - the controller re-resolves
     * options itself server-side (with export_mode forced on) rather than
     * trusting whatever the browser currently has rendered, so the export
     * always reflects the full data set regardless of what's folded/paged
     * in the UI right now. */
    async exportXlsx() {
        await download({
            url: "/account_reports_community_v2/xlsx",
            data: {
                report_id: this.reportId,
                options: JSON.stringify(this.buildOptions()),
            },
        });
    }

    async exportPdf() {
        await download({
            url: "/account_reports_community_v2/pdf",
            data: {
                report_id: this.reportId,
                options: JSON.stringify(this.buildOptions()),
            },
        });
    }

    markFetched(lines) {
        for (const line of lines) {
            if (line.unfolded) {
                line._fetched = true;
            }
            if (line.children && line.children.length) {
                this.markFetched(line.children);
            }
        }
    }

    /** Formats a monetary value using the report's company-currency
     * descriptor (symbol/position/decimal_places) sent from the server -
     * used by every template instead of a bare value.toFixed(2), so
     * amounts read with a currency symbol instead of a naked number. */
    formatAmount(value) {
        if (value === null || value === undefined) {
            return "";
        }
        const currency = (this.state.report && this.state.report.currency) || {};
        const decimals = currency.decimal_places != null ? currency.decimal_places : 2;
        const formatted = value.toFixed(decimals);
        if (!currency.symbol) {
            return formatted;
        }
        return currency.position === "before" ? `${currency.symbol}${formatted}` : `${formatted} ${currency.symbol}`;
    }

    // -- filters shared across every report type (date range/presets, search,
    // journal, posted-vs-all, comparison toggle, partner filter dropdown) ---

    async onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        // A manual edit may no longer be aligned to a calendar month/quarter/
        // year boundary, so comparison falls back to a plain day-count shift.
        this.state.periodGranularity = null;
        await this.loadReport();
    }

    async onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        this.state.periodGranularity = null;
        await this.loadReport();
    }

    togglePresetMenu() {
        this.state.presetMenuOpen = !this.state.presetMenuOpen;
    }

    static formatDate(d) {
        const pad = (n) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    async applyDatePreset(preset) {
        const today = new Date();
        const y = today.getFullYear();
        const m = today.getMonth(); // 0-indexed
        let from;
        let to;
        let granularity;

        if (preset === "today") {
            from = today;
            to = today;
            granularity = null;
        } else if (preset === "this_month") {
            from = new Date(y, m, 1);
            to = new Date(y, m + 1, 0);
            granularity = "month";
        } else if (preset === "last_month") {
            from = new Date(y, m - 1, 1);
            to = new Date(y, m, 0);
            granularity = "month";
        } else if (preset === "this_quarter") {
            const qStart = Math.floor(m / 3) * 3;
            from = new Date(y, qStart, 1);
            to = new Date(y, qStart + 3, 0);
            granularity = "quarter";
        } else if (preset === "last_quarter") {
            const qStart = Math.floor(m / 3) * 3 - 3;
            from = new Date(y, qStart, 1);
            to = new Date(y, qStart + 3, 0);
            granularity = "quarter";
        } else if (preset === "this_year") {
            from = new Date(y, 0, 1);
            to = new Date(y, 11, 31);
            granularity = "year";
        } else if (preset === "last_year") {
            from = new Date(y - 1, 0, 1);
            to = new Date(y - 1, 11, 31);
            granularity = "year";
        } else {
            return;
        }

        this.state.dateFrom = AccountReportAction.formatDate(from);
        this.state.dateTo = AccountReportAction.formatDate(to);
        this.state.periodGranularity = granularity;
        this.state.presetMenuOpen = false;
        await this.loadReport();
    }

    get isPartnerBasedReport() {
        const handler = this.state.report && this.state.report.report_handler;
        return handler === 'partner_ledger' || handler === 'aged_partner_balance';
    }

    get searchPlaceholder() {
        const handler = this.state.report && this.state.report.report_handler;
        if (this.isPartnerBasedReport) {
            return "Search partners...";
        }
        if (handler === "tax_report") {
            return "Search taxes...";
        }
        if (handler === "journal_report") {
            return "Search journals...";
        }
        return "Search accounts...";
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.searchDebounceTimer);
        this.searchDebounceTimer = setTimeout(() => this.loadReport(), 400);
    }

    toggleJournalMenu() {
        this.state.journalMenuOpen = !this.state.journalMenuOpen;
    }

    async toggleJournal(journalId) {
        const index = this.state.journalIds.indexOf(journalId);
        if (index === -1) {
            this.state.journalIds.push(journalId);
        } else {
            this.state.journalIds.splice(index, 1);
        }
        await this.loadReport();
    }

    get journalFilterLabel() {
        if (!this.state.journalIds.length) {
            return "All Journals";
        }
        if (this.state.journalIds.length === 1) {
            const journal = this.state.availableJournals.find((j) => j.id === this.state.journalIds[0]);
            return journal ? journal.name : "1 Journal";
        }
        return `${this.state.journalIds.length} Journals`;
    }

    toggleCurrencyMenu() {
        this.state.currencyMenuOpen = !this.state.currencyMenuOpen;
    }

    async selectCurrency(currencyId) {
        this.state.currencyId = currencyId;
        this.state.currencyMenuOpen = false;
        await this.loadReport();
    }

    /** Unlike the Journal filter (multi-select, "All Journals" when
     * empty), exactly one currency is always active - this label shows
     * that currency's name, resolved server-side to a sensible default
     * (the single selected company's currency, or the active company's
     * when several are selected) until the user picks one explicitly. */
    get currencyFilterLabel() {
        const currency = this.state.availableCurrencies.find((c) => c.id === this.state.currencyId);
        return currency ? currency.name : "Currency";
    }

    async toggleAllEntries() {
        this.state.allEntries = !this.state.allEntries;
        await this.loadReport();
    }

    togglePartnerMenu() {
        this.state.partnerMenuOpen = !this.state.partnerMenuOpen;
    }

    async togglePartnerFilter(partnerId) {
        const index = this.state.partnerIds.indexOf(partnerId);
        if (index === -1) {
            this.state.partnerIds.push(partnerId);
        } else {
            this.state.partnerIds.splice(index, 1);
        }
        await this.loadReport();
    }

    onPartnerFilterQueryInput(ev) {
        this.state.partnerFilterQuery = ev.target.value;
    }

    get filteredAvailablePartners() {
        const query = this.state.partnerFilterQuery.toLowerCase();
        if (!query) {
            return this.state.availablePartners;
        }
        return this.state.availablePartners.filter((p) => p.name.toLowerCase().includes(query));
    }

    get partnerFilterLabel() {
        if (!this.state.partnerIds.length) {
            return "All Partners";
        }
        if (this.state.partnerIds.length === 1) {
            const partner = this.state.availablePartners.find((p) => p.id === this.state.partnerIds[0]);
            return partner ? partner.name : "1 Partner";
        }
        return `${this.state.partnerIds.length} Partners`;
    }

    // -- generic report (Trial Balance / Balance Sheet / P&L) ------------
    // rendered by the account_reports_community_v2.ReportLines template.

    async toggleLine(line) {
        if (!line.foldable) {
            return;
        }
        if (line.unfolded) {
            // Folding never needs new data - just hide what's already rendered.
            line.unfolded = false;
            const index = this.state.unfoldedLineIds.indexOf(line.real_line_id);
            if (index !== -1) {
                this.state.unfoldedLineIds.splice(index, 1);
            }
            return;
        }
        line.unfolded = true;
        if (!this.state.unfoldedLineIds.includes(line.real_line_id)) {
            this.state.unfoldedLineIds.push(line.real_line_id);
        }
        if (!line._fetched) {
            // First time this line is unfolded under the current filters:
            // its children weren't returned by the last fetch, so go get them.
            await this.loadReport();
        }
    }

    async onCellClick(line, column, period) {
        if (column.value === null || column.value === undefined) {
            return;
        }
        await this.openJournalItems(line, column.expression_label, period);
    }

    toggleMenu(line) {
        this.state.openMenuLineId = this.state.openMenuLineId === line.id ? null : line.id;
    }

    async onOpenJournalItems(line) {
        this.state.openMenuLineId = null;
        const lastColumn = (this.state.report.columns || []).at(-1);
        // Kebab menu isn't tied to a specific period column - always drills
        // into the primary (first, non-comparison) period.
        await this.openJournalItems(line, lastColumn ? lastColumn.expression_label : null);
    }

    async openJournalItems(line, expressionLabel, period) {
        if (!expressionLabel) {
            return;
        }
        const options = this.buildOptions();
        if (period) {
            options.date_from = period.date_from;
            options.date_to = period.date_to;
        }
        const params = {
            options,
            expression_label: expressionLabel,
        };
        if (line.account_id) {
            params.account_id = line.account_id;
        }
        const action = await this.orm.call(
            "account.report.line",
            "action_get_drilldown",
            [[line.real_line_id]],
            params,
        );
        this.actionService.doAction(action);
    }

    async onOpenGeneralLedger(line) {
        this.state.openMenuLineId = null;
        const glReportId = this.state.report.general_ledger_report_id;
        if (!glReportId || !line.account_id) {
            return;
        }
        await this.actionService.doAction({
            type: "ir.actions.client",
            tag: "account_report_community",
            name: "General Ledger",
            context: {
                report_id: glReportId,
                focus_account_id: line.account_id,
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
            },
        });
    }

    // -- General Ledger ---------------------------------------------------
    // rendered by general_ledger_table.xml's GeneralLedgerLines template.

    async toggleGeneralLedgerAccount(line) {
        if (line.unfolded) {
            // Folding never needs new data - just hide what's already rendered.
            line.unfolded = false;
            const index = this.state.unfoldedLineIds.indexOf(line.account_id);
            if (index !== -1) {
                this.state.unfoldedLineIds.splice(index, 1);
            }
            return;
        }
        line.unfolded = true;
        if (!this.state.unfoldedLineIds.includes(line.account_id)) {
            this.state.unfoldedLineIds.push(line.account_id);
        }
        if (!line._fetched) {
            // First time this account is unfolded under the current filters:
            // its journal items weren't returned by the last fetch, so go get them.
            await this.loadReport();
        }
    }

    // -- Partner Ledger & Aged Receivable/Payable -------------------------
    // Both group by partner_id (partner_ledger_table.xml /
    // aged_balance_table.xml), so they share this fold/drill-down logic.

    async togglePartnerLedgerPartner(line) {
        if (line.unfolded) {
            // Folding never needs new data - just hide what's already rendered.
            line.unfolded = false;
            const index = this.state.unfoldedLineIds.indexOf(line.partner_id);
            if (index !== -1) {
                this.state.unfoldedLineIds.splice(index, 1);
            }
            return;
        }
        line.unfolded = true;
        if (!this.state.unfoldedLineIds.includes(line.partner_id)) {
            this.state.unfoldedLineIds.push(line.partner_id);
        }
        if (!line._fetched) {
            // First time this partner is unfolded under the current filters:
            // their journal items weren't returned by the last fetch, so go get them.
            await this.loadReport();
        }
    }

    onOpenPartnerJournalItems(line) {
        // Unlike the ledger view itself (receivable/payable only), this
        // opens every journal item for the partner regardless of account -
        // still scoped to the currently selected date range/journal/
        // posted-vs-all filters, since that's the period the user is
        // actually looking at.
        const domain = [["partner_id", "=", line.partner_id]];
        if (this.state.dateFrom) {
            domain.push(["date", ">=", this.state.dateFrom]);
        }
        if (this.state.dateTo) {
            domain.push(["date", "<=", this.state.dateTo]);
        }
        if (!this.state.allEntries) {
            domain.push(["parent_state", "=", "posted"]);
        }
        if (this.state.journalIds.length) {
            domain.push(["journal_id", "in", [...this.state.journalIds]]);
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: `${line.name} — Journal Items`,
            res_model: "account.move.line",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    // -- Tax Report --------------------------------------------------------
    // rendered by tax_report_table.xml's TaxReportLines template.

    async toggleTaxReportTax(line) {
        if (line.unfolded) {
            line.unfolded = false;
            const index = this.state.unfoldedLineIds.indexOf(line.tax_id);
            if (index !== -1) {
                this.state.unfoldedLineIds.splice(index, 1);
            }
            return;
        }
        line.unfolded = true;
        if (!this.state.unfoldedLineIds.includes(line.tax_id)) {
            this.state.unfoldedLineIds.push(line.tax_id);
        }
        if (!line._fetched) {
            await this.loadReport();
        }
    }

    onOpenTaxJournalItems(line) {
        const domain = [["tax_line_id", "=", line.tax_id]];
        if (this.state.dateFrom) {
            domain.push(["date", ">=", this.state.dateFrom]);
        }
        if (this.state.dateTo) {
            domain.push(["date", "<=", this.state.dateTo]);
        }
        if (!this.state.allEntries) {
            domain.push(["parent_state", "=", "posted"]);
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: `${line.name} — Journal Items`,
            res_model: "account.move.line",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    // -- Journal Report ----------------------------------------------------
    // rendered by journal_report_table.xml's JournalReportLines template.

    async toggleJournalReportJournal(line) {
        if (line.unfolded) {
            line.unfolded = false;
            const index = this.state.unfoldedLineIds.indexOf(line.journal_id);
            if (index !== -1) {
                this.state.unfoldedLineIds.splice(index, 1);
            }
            return;
        }
        line.unfolded = true;
        if (!this.state.unfoldedLineIds.includes(line.journal_id)) {
            this.state.unfoldedLineIds.push(line.journal_id);
        }
        if (!line._fetched) {
            await this.loadReport();
        }
    }

    // -- shared "Load more" pagination (any report's raw journal-item rows) -
    // One group_id field per report_handler (account_id/partner_id/tax_id/
    // journal_id); GL and Partner Ledger also carry a running_balance that
    // has to be continued from the last row already on screen, and Aged
    // Balance's server-side cursor sorts by due date rather than plain
    // date, so it needs its own extra param. Keyset pagination (based on
    // the last row's own date/id, not an OFFSET count) so "Load more"
    // stays equally fast no matter how many pages came before it.

    async loadMoreAmlRows(line) {
        const rows = line.aml_rows;
        const lastRow = rows[rows.length - 1];
        if (!lastRow) {
            return;
        }
        const handler = this.state.report.report_handler;
        const groupIdByHandler = {
            general_ledger: line.account_id,
            partner_ledger: line.partner_id,
            aged_partner_balance: line.partner_id,
            tax_report: line.tax_id,
            journal_report: line.journal_id,
        };
        const params = {
            options: this.buildOptions(),
            group_id: groupIdByHandler[handler],
            after_id: lastRow.id,
            after_date: lastRow.date,
        };
        if (handler === "general_ledger" || handler === "partner_ledger") {
            params.after_running_balance = lastRow.running_balance;
        }
        if (handler === "aged_partner_balance") {
            params.after_maturity = lastRow.due_date;
        }

        this.state.loadingMoreLineId = line.id;
        try {
            const result = await this.orm.call(
                "account.report",
                "action_get_more_aml_rows",
                [[this.reportId]],
                params,
            );
            line.aml_rows.push(...result.aml_rows);
            line.aml_rows_has_more = result.aml_rows_has_more;
        } finally {
            this.state.loadingMoreLineId = null;
        }
    }

    // -- shared navigation (any report's raw journal-item rows) ----------

    onOpenMove(row) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: row.move_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("account_report_community", AccountReportAction);
