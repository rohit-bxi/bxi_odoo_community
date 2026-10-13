/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

// Sections of the claim form shown for each conveyance type. An element of several sections is shown when
// any of them applies.
const SECTIONS = {
    lc_trip: ["vehicle_2w", "vehicle_4w", "auto", "taxi"],
    lc_transfer: ["transfer_2w", "transfer_4w"],
    lc_emergency: ["auto"],
    lc_reason: ["auto", "taxi"],
    lc_parking: ["parking_toll"],
    lc_bill: ["auto", "taxi", "parking_toll", "food"],
    lc_food: ["food"],
};

publicWidget.registry.ConveyanceForm = publicWidget.Widget.extend({
    selector: "#conveyance_form",
    events: {
        "change #lc_product": "_update",
        "change #lc_purpose": "_update",
    },

    start() {
        this._update();
        return this._super(...arguments);
    },

    _update() {
        const option = this.el.querySelector("#lc_product").selectedOptions[0];
        const kind = option ? option.dataset.kind || "" : "";
        const shown = new Map();
        for (const [section, kinds] of Object.entries(SECTIONS)) {
            this.el.querySelectorAll(`.${section}`).forEach((el) => {
                shown.set(el, shown.get(el) || kinds.includes(kind));
            });
        }
        shown.forEach((visible, el) => el.classList.toggle("d-none", !visible));
        const isTrip = SECTIONS.lc_trip.includes(kind);
        const isAirport = isTrip && this.el.querySelector("#lc_purpose").value === "airport";
        this.el.querySelectorAll(".lc_airport").forEach((el) => el.classList.toggle("d-none", !isAirport));
        // Personal vehicles are paid per km: the distance is what counts.
        this.el.querySelector("#lc_distance").required = [
            "vehicle_2w", "vehicle_4w", "transfer_2w", "transfer_4w",
        ].includes(kind);
        this.el.querySelector("#lc_transfer").required = SECTIONS.lc_transfer.includes(kind);
        this.el.querySelector("#lc_amount").required = SECTIONS.lc_bill.includes(kind);
    },
});
