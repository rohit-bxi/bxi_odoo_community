/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class BxiTimesheetDashboard extends Component {
    static template = "bxi_timesheet.TimesheetDashboardTemplate";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loaded: false,
            employee_id: false,
            employee_name: "",
            is_manager: false,
            is_hr: false,
            is_admin: false,
            dates: [],
            grid_lines: [],
            daily_totals: [],
            overall_total: "0:00",
            employee_options: [],
            projects: [],
            tasks: [],
            team_summary: [],
            filter_type: "own", // "own" or "team"
            start_date_str: "",
            selected_employee_id: "",
            check_in_row: [],
            check_out_row: [],
            draft_count: 0,
            submitted_count: 0,
            approved_count: 0,
            refused_count: 0,
            is_target_employee_manager: false,
            is_past_week: false,
            total_prod_str: "0:00",
            total_shift_prod_str: "0:00",
            total_shift_str: "0:00",

            // L1 & L2 reference data
            categories: [],
            crm_leads: [],
            allocated_projects: [],

            // Modal states for 3 Levels
            show_add_row_modal: false,
            new_row_category_id: "",
            new_row_activity_id: "",
            activity_search_query: "",
            new_row_description: "",
            new_row_date: "",
            new_row_hours: "",
        });

        onWillStart(async () => {
            // Default start date is this week's Sunday
            const today = new Date();
            const sunday = new Date(today);
            sunday.setDate(today.getDate() - today.getDay());
            this.state.start_date_str = this.formatDateStr(sunday);

            await this.loadData();
        });
    }

    formatDateStr(dateObj) {
        const year = dateObj.getFullYear();
        const month = String(dateObj.getMonth() + 1).padStart(2, '0');
        const day = String(dateObj.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    getRowBadge(index) {
        return String.fromCharCode(97 + (index % 26));
    }

    async loadData() {
        this.state.loaded = false;
        try {
            const result = await this.orm.call(
                "bxi.timesheet.dashboard",
                "get_dashboard_data",
                [],
                {
                    employee_id: this.state.selected_employee_id || null,
                    start_date_str: this.state.start_date_str,
                    filter_type: this.state.filter_type,
                }
            );

            this.state.employee_id = result.employee_id;
            this.state.employee_name = result.employee_name;
            this.state.is_manager = result.is_manager;
            this.state.is_hr = result.is_hr;
            this.state.is_admin = result.is_admin;
            this.state.dates = result.dates;
            this.state.grid_lines = result.grid_lines;
            this.state.daily_totals = result.daily_totals;
            this.state.overall_total = result.overall_total;
            this.state.employee_options = result.employee_options;
            this.state.team_summary = result.team_summary;
            this.state.projects = result.projects || [];
            this.state.tasks = result.tasks || [];
            this.state.start_date_str = result.start_date_str;
            this.state.is_target_employee_manager = result.is_target_employee_manager || false;
            this.state.is_past_week = result.is_past_week || false;
            this.state.total_prod_str = result.total_prod_str || "0:00";
            this.state.total_shift_prod_str = result.total_shift_prod_str || "0:00";
            this.state.total_shift_str = result.total_shift_str || "0:00";
            this.state.draft_count = result.draft_count || 0;
            this.state.submitted_count = result.submitted_count || 0;
            this.state.approved_count = result.approved_count || 0;
            this.state.refused_count = result.refused_count || 0;

            this.state.categories = result.categories || [];
            this.state.crm_leads = result.crm_leads || [];
            this.state.allocated_projects = result.allocated_projects || [];

            // Set selected employee ID to default if not set
            if (!this.state.selected_employee_id && result.employee_id) {
                this.state.selected_employee_id = String(result.employee_id);
            }

            this.state.loaded = true;
        } catch (error) {
            console.error("Error loading timesheet dashboard data:", error);
            this.state.loaded = true;
        }
    }

    async navigateWeek(offset) {
        const parts = this.state.start_date_str.split('-');
        const year = parseInt(parts[0], 10);
        const month = parseInt(parts[1], 10) - 1;
        const day = parseInt(parts[2], 10);

        let currentDate = new Date(year, month, day);
        currentDate.setDate(currentDate.getDate() + (offset * 7));

        this.state.start_date_str = this.formatDateStr(currentDate);
        await this.loadData();
    }

    async goToToday() {
        const today = new Date();
        const sunday = new Date(today);
        sunday.setDate(today.getDate() - today.getDay());

        this.state.start_date_str = this.formatDateStr(sunday);
        await this.loadData();
    }

    async setFilterType(type) {
        this.state.filter_type = type;
        await this.loadData();
    }

    async onEmployeeChange(ev) {
        this.state.selected_employee_id = ev.target.value;
        await this.loadData();
    }

    async onCellBlur(ev, line, dateStr) {
        const value = ev.target.value.trim();

        try {
            await this.orm.call(
                "bxi.timesheet.dashboard",
                "save_timesheet_hours",
                [],
                {
                    employee_id: parseInt(this.state.selected_employee_id),
                    date_str: dateStr,
                    amount_str: value,
                    description: line.description || false,
                    category_id: line.category_id || false,
                    activity_id: line.activity_id || false,
                    lead_id: line.lead_id || false,
                    project_id: line.project_id || false,
                    task_id: line.task_id || false,
                    l2_type: line.l2_type || false,
                    l2_id: line.l2_id || false,
                }
            );
            await this.loadData();
        } catch (error) {
            console.error("Error saving timesheet hours:", error);
            const msg = error?.data?.message || error?.message || "Error saving timesheet hours.";
            if (this.notification) {
                this.notification.add(msg, { title: "Warning", type: "warning" });
            }
            await this.loadData();
        }
    }

    async openAddRowModal() {
        if (!this.state.categories || this.state.categories.length === 0) {
            await this.loadData();
        }

        // Set default category
        const defaultCat = this.state.categories && this.state.categories.length > 0 ? this.state.categories[0] : null;
        this.state.new_row_category_id = defaultCat ? String(defaultCat.id) : "";
        this.state.activity_search_query = "";

        // Set default activity (prefer "Other", or first available)
        this.resetDefaultActivity();

        this.state.new_row_description = "";
        this.state.new_row_date = this.formatDateStr(new Date());
        this.state.new_row_hours = "";
        this.state.show_add_row_modal = true;
    }

    resetDefaultActivity() {
        const acts = this.availableActivities;
        const otherAct = acts.find(a => a.name.toLowerCase() === 'other');
        if (otherAct) {
            this.state.new_row_activity_id = String(otherAct.id);
        } else if (acts.length > 0) {
            this.state.new_row_activity_id = String(acts[0].id);
        } else {
            this.state.new_row_activity_id = "";
        }
    }

    closeAddRowModal() {
        this.state.show_add_row_modal = false;
    }

    get selectedCategory() {
        if (!this.state.new_row_category_id) return null;
        const catId = parseInt(this.state.new_row_category_id, 10);
        return (this.state.categories || []).find(c => c.id === catId) || null;
    }

    get availableActivities() {
        const cat = this.selectedCategory;
        if (!cat) return [];

        // 1. Revenue Generation: Own CRM Leads / Opportunities
        if (cat.is_crm || cat.code === 'revenue_generation') {
            const list = (this.state.crm_leads || []).map(l => ({
                id: 'lead_' + l.id,
                l2_type: 'lead',
                l2_id: l.id,
                name: l.name,
            }));
            list.push({
                id: 'other',
                l2_type: 'activity',
                l2_id: 'other',
                name: 'Other',
            });
            return list;
        }

        // 2. Delivery / Project Execution: Assigned Projects based on Allocations
        if (cat.is_project || cat.code === 'delivery_project') {
            const list = (this.state.allocated_projects || []).map(p => ({
                id: 'proj_' + p.id,
                l2_type: 'project',
                l2_id: p.id,
                name: p.name,
            }));
            list.push({
                id: 'other',
                l2_type: 'activity',
                l2_id: 'other',
                name: 'Other',
            });
            return list;
        }

        // 3. Predefined Activities for Category
        const list = (cat.activities || []).map(a => ({
            id: String(a.id),
            l2_type: 'activity',
            l2_id: a.id,
            name: a.name,
        }));
        if (!list.some(a => a.name.toLowerCase() === 'other')) {
            list.push({
                id: 'other',
                l2_type: 'activity',
                l2_id: 'other',
                name: 'Other',
            });
        }
        return list;
    }

    get filteredActivities() {
        const q = (this.state.activity_search_query || "").trim().toLowerCase();
        const acts = this.availableActivities;
        if (!q) return acts;
        return acts.filter(a => a.name.toLowerCase().includes(q));
    }

    get wordCount() {
        const val = (this.state.new_row_description || "").trim();
        if (!val) return 0;
        return val.split(/\s+/).filter(Boolean).length;
    }

    get newRowCategoryError() {
        if (!this.state.new_row_category_id) {
            return "Category (L1) is required.";
        }
        return "";
    }

    get newRowActivityError() {
        if (!this.state.new_row_activity_id) {
            return "Activity (L2) is mandatory.";
        }
        return "";
    }

    get newRowDescriptionError() {
        const val = (this.state.new_row_description || "").trim();
        if (!val) {
            return "Task Description (L3) is required.";
        }
        if (this.wordCount > 100) {
            return `Task description cannot exceed 100 words (current: ${this.wordCount} words).`;
        }
        return "";
    }

    get newRowHoursError() {
        const val = (this.state.new_row_hours || "").trim();
        if (!val) {
            return "Time Spent (Hours) is required.";
        }
        let hours = 0.0;
        if (val.includes(':')) {
            const parts = val.split(':');
            const h = parseInt(parts[0], 10) || 0;
            const m = parseInt(parts[1], 10) || 0;
            hours = h + (m / 60.0);
        } else {
            hours = parseFloat(val) || 0.0;
        }
        if (isNaN(hours) || hours <= 0.0) {
            return "Time Spent must be greater than 0:00.";
        }
        if (hours > 9.0) {
            return "You cannot log more than 9 hours for a single day.";
        }

        // Validate daily total does not exceed 9.0 hours across the day's entries
        const targetDateStr = this.state.new_row_date;
        if (targetDateStr && this.state.grid_lines && this.state.grid_lines.length > 0) {
            let existingHours = 0.0;
            for (const line of this.state.grid_lines) {
                const day = line.days_data && line.days_data.find(d => d.date_str === targetDateStr);
                if (day && day.hours_raw > 0.0) {
                    existingHours += day.hours_raw;
                }
            }
            if (existingHours + hours > 9.001) {
                return `Total timesheet hours for ${targetDateStr} cannot exceed 9 hours (Already logged: ${existingHours.toFixed(2)} hrs, Attempting to add: ${hours.toFixed(2)} hrs, Total: ${(existingHours + hours).toFixed(2)} hrs).`;
            }
        }
        return "";
    }

    get newRowDateError() {
        const targetDateStr = this.state.new_row_date;
        if (!targetDateStr) {
            return "Date is required.";
        }

        const parts = targetDateStr.split('-');
        if (parts.length !== 3) return "";
        const year = parseInt(parts[0], 10);
        const month = parseInt(parts[1], 10) - 1;
        const day = parseInt(parts[2], 10);
        const targetDate = new Date(year, month, day);
        targetDate.setHours(0, 0, 0, 0);

        const today = new Date();
        const sunday = new Date(today);
        sunday.setDate(today.getDate() - today.getDay());
        sunday.setHours(0, 0, 0, 0);

        // if (targetDate < sunday) {
        //     return "Timesheets for previous weeks cannot be created or modified.";
        // }
        return "";
    }

    onCategoryChange(ev) {
        this.state.new_row_category_id = ev.target.value;
        this.state.activity_search_query = "";
        this.resetDefaultActivity();
    }

    onActivitySearch(ev) {
        this.state.activity_search_query = ev.target.value;
    }

    onActivityChange(ev) {
        this.state.new_row_activity_id = ev.target.value;
    }

    onDescriptionChange(ev) {
        this.state.new_row_description = ev.target.value;
    }

    onDateChange(ev) {
        this.state.new_row_date = ev.target.value;
    }

    onHoursChange(ev) {
        this.state.new_row_hours = ev.target.value;
    }

    async confirmAddRow() {
        const validationError = this.newRowCategoryError || this.newRowActivityError || this.newRowDescriptionError || this.newRowDateError || this.newRowHoursError;
        if (validationError) {
            if (this.notification) {
                this.notification.add(validationError, { title: "Validation Error", type: "warning" });
            }
            return;
        }

        let empId = parseInt(this.state.selected_employee_id) || 0;
        if (!empId && this.state.employee_options && this.state.employee_options.length > 0) {
            empId = parseInt(this.state.employee_options[0].id) || 0;
        }

        // Find the selected activity object to determine whether it is lead, project, or predefined activity
        const actVal = this.state.new_row_activity_id;
        const selectedAct = this.availableActivities.find(a => String(a.id) === String(actVal));

        const catId = parseInt(this.state.new_row_category_id, 10) || false;
        let l2_type = selectedAct ? selectedAct.l2_type : 'activity';
        let l2_id = selectedAct ? selectedAct.l2_id : false;

        let actId = false;
        let leadId = false;
        let projId = false;

        if (l2_type === 'lead') {
            leadId = l2_id;
        } else if (l2_type === 'project') {
            projId = l2_id;
        } else if (l2_type === 'activity') {
            actId = l2_id;
        }

        try {
            await this.orm.call(
                "bxi.timesheet.dashboard",
                "save_timesheet_hours",
                [],
                {
                    employee_id: empId || false,
                    date_str: this.state.new_row_date,
                    amount_str: this.state.new_row_hours || "0:00",
                    description: this.state.new_row_description.trim(),
                    category_id: catId,
                    activity_id: actId,
                    lead_id: leadId,
                    project_id: projId,
                    l2_type: l2_type,
                    l2_id: l2_id,
                }
            );
            await this.loadData();
            this.closeAddRowModal();
        } catch (error) {
            console.error("Error adding timesheet line:", error);
            const msg = error?.data?.message || error?.message || "Error adding timesheet line.";
            if (this.notification) {
                this.notification.add(msg, { title: "Error", type: "danger" });
            }
        }
    }

    async submitTimesheet() {
        try {
            await this.orm.call(
                "bxi.timesheet.dashboard",
                "submit_weekly_timesheet",
                [],
                {
                    employee_id: parseInt(this.state.selected_employee_id),
                    start_date_str: this.state.start_date_str,
                }
            );
            await this.loadData();
            if (this.notification) {
                this.notification.add(
                    "Weekly timesheet submitted successfully for approval.",
                    { title: "Submitted", type: "success" }
                );
            }
        } catch (error) {
            console.error("Error submitting timesheet:", error);
            const errorMessage = error?.data?.message || error?.data?.debug || error?.message || "Error submitting timesheet.";
            if (this.notification) {
                this.notification.add(
                    errorMessage,
                    { title: "Error", type: "danger" }
                );
            }
        }
    }

    async approveTimesheet() {
        try {
            await this.orm.call(
                "bxi.timesheet.dashboard",
                "approve_weekly_timesheet",
                [],
                {
                    employee_id: parseInt(this.state.selected_employee_id),
                    start_date_str: this.state.start_date_str,
                }
            );
            await this.loadData();
        } catch (error) {
            console.error("Error approving timesheet:", error);
        }
    }

    async refuseTimesheet() {
        try {
            await this.orm.call(
                "bxi.timesheet.dashboard",
                "refuse_weekly_timesheet",
                [],
                {
                    employee_id: parseInt(this.state.selected_employee_id),
                    start_date_str: this.state.start_date_str,
                }
            );
            await this.loadData();
        } catch (error) {
            console.error("Error refusing timesheet:", error);
        }
    }
}

registry.category("actions").add("bxi_timesheet_dashboard_tag", BxiTimesheetDashboard);
export { BxiTimesheetDashboard };
