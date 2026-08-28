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
            total_shift_str: "0:00",

            // Modal states
            show_add_row_modal: false,
            new_row_project_id: "",
            new_row_task_id: "",
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
            this.state.projects = result.projects;
            this.state.tasks = result.tasks;
            this.state.start_date_str = result.start_date_str;
            this.state.is_target_employee_manager = result.is_target_employee_manager || false;
            this.state.is_past_week = result.is_past_week || false;
            this.state.total_prod_str = result.total_prod_str || "0:00";
            this.state.total_shift_str = result.total_shift_str || "0:00";
            this.state.draft_count = result.draft_count || 0;
            this.state.submitted_count = result.submitted_count || 0;
            this.state.approved_count = result.approved_count || 0;
            this.state.refused_count = result.refused_count || 0;



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

        // Optimistic local feedback if format is wrong, or save to backend
        try {
            await this.orm.call(
                "bxi.timesheet.dashboard",
                "save_timesheet_hours",
                [],
                {
                    employee_id: parseInt(this.state.selected_employee_id),
                    date_str: dateStr,
                    project_id: line.project_id || false,
                    task_id: line.task_id || false,
                    amount_str: value,
                    description: line.description || false,
                }
            );
            // Reload to recalculate totals and normalize formats (e.g. "2" becomes "2:00")
            await this.loadData();
        } catch (error) {
            console.error("Error saving timesheet hours:", error);
            // Revert value
            await this.loadData();
        }
    }

    async openAddRowModal() {
        this.state.new_row_project_id = "";
        this.state.new_row_task_id = "";
        this.state.new_row_description = "";
        this.state.new_row_date = this.formatDateStr(new Date());
        this.state.new_row_hours = "";
        if (!this.state.projects || this.state.projects.length === 0) {
            await this.loadData();
        }
        this.state.show_add_row_modal = true;
    }

    closeAddRowModal() {
        this.state.show_add_row_modal = false;
    }

    get filteredTasks() {
        if (!this.state.new_row_project_id) {
            return [];
        }
        const selectedProjId = parseInt(this.state.new_row_project_id, 10);
        return (this.state.tasks || []).filter(t => {
            if (!t.project_id) return false;
            if (Array.isArray(t.project_id)) {
                return t.project_id[0] === selectedProjId;
            }
            return parseInt(t.project_id, 10) === selectedProjId;
        });
    }

    get newRowProjectError() {
        if (!this.state.new_row_project_id) {
            return "Project is required.";
        }
        return "";
    }

    get newRowTaskError() {
        if (!this.state.new_row_task_id) {
            return "Task is required.";
        }
        return "";
    }

    get newRowDescriptionError() {
        const val = (this.state.new_row_description || "").trim();
        if (!val) {
            return "Description / Notes is required.";
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
        if (hours > 9.0) {
            return "Hours cannot exceed 9:00 hours per day.";
        }
        return "";
    }

    get newRowDateError() {
        if (!this.state.new_row_date) {
            return "Date is required.";
        }
        const targetDateStr = this.state.new_row_date;

        // Check if any line on this date is already submitted or approved
        if (this.state.grid_lines && this.state.grid_lines.length > 0) {
            const dateIdx = (this.state.dates || []).findIndex(d => d.date_str === targetDateStr);
            if (dateIdx !== -1) {
                const isAlreadySubmitted = this.state.grid_lines.some(line => {
                    const st = line.states ? line.states[dateIdx] : false;
                    return st === 'submitted' || st === 'approved';
                });
                if (isAlreadySubmitted && !(this.state.is_manager || this.state.is_hr || this.state.is_admin)) {
                    return `Timesheet for ${targetDateStr} has already been submitted or approved.`;
                }
            }
        }

        const parts = targetDateStr.split('-');
        if (parts.length !== 3) return "";
        const year = parseInt(parts[0], 10);
        const month = parseInt(parts[1], 10) - 1;
        const day = parseInt(parts[2], 10);
        const targetDate = new Date(year, month, day);
        targetDate.setHours(0, 0, 0, 0);

        // Find preceding Sunday for today
        const today = new Date();
        const sunday = new Date(today);
        sunday.setDate(today.getDate() - today.getDay());
        sunday.setHours(0, 0, 0, 0);

        if (targetDate < sunday) {
            return "Timesheets for previous weeks cannot be created or modified.";
        }
        return "";
    }

    onProjectChange(ev) {
        this.state.new_row_project_id = ev.target.value;
        this.state.new_row_task_id = "";
    }

    onTaskChange(ev) {
        this.state.new_row_task_id = ev.target.value;
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
        if (this.newRowProjectError || this.newRowTaskError || this.newRowDescriptionError || this.newRowDateError || this.newRowHoursError) {
            if (this.notification) {
                this.notification.add(
                    this.newRowProjectError || this.newRowTaskError || this.newRowDescriptionError || this.newRowDateError || this.newRowHoursError,
                    { title: "Required Field", type: "warning" }
                );
            }
            return;
        }

        const projId = parseInt(this.state.new_row_project_id) || 0;
        const tskId = parseInt(this.state.new_row_task_id) || 0;

        let empId = parseInt(this.state.selected_employee_id) || 0;
        if (!empId && this.state.employee_options && this.state.employee_options.length > 0) {
            empId = parseInt(this.state.employee_options[0].id) || 0;
        }

        try {
            await this.orm.call(
                "bxi.timesheet.dashboard",
                "save_timesheet_hours",
                [],
                {
                    employee_id: empId || false,
                    date_str: this.state.new_row_date,
                    project_id: projId,
                    task_id: tskId,
                    amount_str: this.state.new_row_hours || "0:00",
                    description: this.state.new_row_description || false,
                }
            );
            await this.loadData();
            this.closeAddRowModal();
        } catch (error) {
            console.error("Error adding timesheet line:", error);
            if (this.notification) {
                this.notification.add(
                    error.message || "Error adding timesheet line.",
                    { title: "Error", type: "danger" }
                );
            }
        }
    }

    async submitTimesheet() {
        if (this.state.is_past_week && !(this.state.is_target_employee_manager || this.state.is_hr || this.state.is_admin)) {
            if (this.notification) {
                this.notification.add(
                    "Once a week is crossed, timesheets for the previous week cannot be submitted.",
                    { title: "Submission Blocked", type: "danger" }
                );
            }
            return;
        }

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
            if (this.notification) {
                this.notification.add(
                    error.message || "Error submitting timesheet.",
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
