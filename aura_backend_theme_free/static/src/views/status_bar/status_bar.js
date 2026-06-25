/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

/**
 * Override adjustVisibleItems to always keep all steps inline.
 * Odoo's default collapses steps into a dropdown when the container
 * is too narrow or env.isSmall is true — we skip that logic entirely
 * and let CSS flex-wrap handle overflow instead.
 */
patch(StatusBarField.prototype, {
    adjustVisibleItems() {
        const root = this.rootRef.el;
        if (!root) return;

        const itemEls = [
            ...root.querySelectorAll(".o_arrow_button:not(.dropdown-toggle)"),
        ];

        // Show all inline buttons
        itemEls.forEach((el) => el.classList.remove("d-none"));

        // Hide the before (overflow-left) and single-all-items dropdowns
        this.beforeRef.el?.classList.add("d-none");
        this.dropdownRef.el?.classList.add("d-none");

        // Only keep the "after" dropdown visible if there are folded items (fold_field)
        this.items.before = [];
        this.items.after = [...(this.items.folded || [])];

        if (this.items.folded.length) {
            this.afterRef.el?.classList.remove("d-none");
            itemEls.forEach((el) => el.classList.remove("o_first"));
        } else {
            this.afterRef.el?.classList.add("d-none");
            // DOM-first button = visual-last — needs o_first for correct pill shape
            itemEls[0]?.classList.add("o_first");
        }
    },
});

/**
 * Marks step buttons with tbt-step-done / tbt-step-future classes.
 *
 * Odoo renders inline buttons in REVERSED DOM order and relies on
 * flex-flow: row-reverse to restore visual order. This means:
 *   DOM index > currentIndex  →  visually BEFORE current  →  completed
 *   DOM index < currentIndex  →  visually AFTER current   →  future
 */
function markSteps(statusbar) {
    const buttons = [
        ...statusbar.querySelectorAll(
            ".o_arrow_button:not(.dropdown-toggle):not(.d-none)"
        ),
    ];
    const currentIdx = buttons.findIndex((btn) =>
        btn.classList.contains("o_arrow_button_current")
    );
    buttons.forEach((btn, i) => {
        btn.classList.remove("tbt-step-done", "tbt-step-future");
        if (currentIdx < 0) return;
        if (i > currentIdx) btn.classList.add("tbt-step-done");
        else if (i < currentIdx) btn.classList.add("tbt-step-future");
    });
}

function initAll() {
    document.querySelectorAll(".o_statusbar_status").forEach(markSteps);
}

const observer = new MutationObserver(initAll);

function start() {
    const target = document.body || document.documentElement;
    if (!target) return;
    initAll();
    observer.observe(target, { childList: true, subtree: true });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
} else {
    start();
}
