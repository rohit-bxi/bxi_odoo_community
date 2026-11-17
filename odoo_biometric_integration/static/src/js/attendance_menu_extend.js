/** @odoo-module **/

import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";
import { patch } from "@web/core/utils/patch";

// Employees whose attendance comes from the biometric device (linked to a device,
// working at a Biometric Attendance Only location today) get no systray check
// in/out. This runs for the page-load data, the dropdown refresh and the check
// in/out response alike.
patch(ActivityMenu.prototype, {
    _searchReadEmployeeFill() {
        super._searchReadEmployeeFill();
        if (this.employee?.manual_attendance_allowed === false) {
            this.state.isDisplayed = false;
        }
    },
});
