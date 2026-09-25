/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PerformanceReviewScreen extends Component {
    static template = "bxi_performance_review_owl.PerformanceReviewScreen";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            saving: false,
            filter: "my",
            reviews: [],
            review: null,
            lines: [],
            error: null,
        });
        onWillStart(() => this.loadReviews());
    }

    async loadReviews() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const uid = await this.orm.call("performance.review", "get_current_user_id", []);
            const domain = this.state.filter === "approve"
                ? ["|", ["manager_user_id", "=", uid], ["second_manager_user_id", "=", uid]]
                : [["employee_user_id", "=", uid]];

            this.state.reviews = await this.orm.searchRead(
                "performance.review",
                domain,
                [
                    "id", "name", "employee_id", "period_id", "state",
                    "year", "quarter", "final_score",
                ],
                { order: "id desc", limit: 100 }
            );

            if (this.state.reviews.length) {
                const currentId = this.state.review && this.state.reviews.some(
                    (review) => review.id === this.state.review.id
                ) ? this.state.review.id : this.state.reviews[0].id;
                await this.loadReview(currentId);
            } else {
                this.state.review = null;
                this.state.lines = [];
            }
        } catch (error) {
            this.state.error = error?.message || "Unable to load Performance Reviews.";
            this.state.review = null;
            this.state.lines = [];
        } finally {
            this.state.loading = false;
        }
    }

    async loadReview(id) {
        const result = await this.orm.searchRead(
            "performance.review",
            [["id", "=", id]],
            [
                "id", "name", "employee_id", "employee_email", "manager_id",
                "manager_email", "second_manager_id", "second_manager_email",
                "period_id", "template_id", "company_id", "company_logo", "state",
                "year", "quarter", "final_score", "successor_1", "successor_2",
                "appraisee_remarks", "manager_remarks", "calibration",
                "reviewer_remarks", "employee_submitted_date",
                "manager_submitted_date", "second_manager_submitted_date",
                "completed_date", "can_edit_self", "can_edit_manager",
                "can_edit_second", "can_edit_hr", "line_ids",
            ]
        );

        if (!result.length) {
            this.state.review = null;
            this.state.lines = [];
            return;
        }

        this.state.review = result[0];
        this.state.lines = this.state.review.line_ids?.length
            ? await this.orm.read(
                "performance.review.line",
                this.state.review.line_ids,
                [
                    "id", "sequence", "category", "weightage", "target",
                    "description", "self_achievement", "manager_review",
                    "manager_score",
                ]
            )
            : [];
    }

    onFilterChange(filter) {
        this.state.filter = filter;
        this.loadReviews();
    }

    onReviewChange(ev) {
        const id = Number(ev.target.value);
        if (id) {
            this.loadReview(id);
        }
    }

    isSelfEditable() {
        return false;
    }

    isManagerEditable() {
        return false;
    }

    isSecondEditable() {
        return false;
    }

    async save() {
        if (!this.state.review || this.state.saving) {
            return;
        }

        this.state.saving = true;
        try {
            const review = this.state.review;
            const values = {};

            if (this.isSelfEditable()) {
                values.successor_1 = review.successor_1 || false;
                values.successor_2 = review.successor_2 || false;
                values.appraisee_remarks = review.appraisee_remarks || false;
            }

            if (this.isManagerEditable()) {
                values.manager_remarks = review.manager_remarks || false;
            }

            if (this.isSecondEditable()) {
                values.calibration = review.calibration === ""
                    ? false
                    : Number(review.calibration || 0);
                values.reviewer_remarks = review.reviewer_remarks || false;
            }

            if (Object.keys(values).length) {
                await this.orm.write("performance.review", [review.id], values);
            }

            for (const line of this.state.lines) {
                const lineValues = {};

                if (this.isSelfEditable()) {
                    lineValues.self_achievement = line.self_achievement || false;
                }

                if (this.isManagerEditable()) {
                    lineValues.manager_review = line.manager_review || false;
                    lineValues.manager_score = (
                        line.manager_score === "" || line.manager_score == null
                    ) ? false : line.manager_score;
                }

                if (Object.keys(lineValues).length) {
                    await this.orm.write("performance.review.line", [line.id], lineValues);
                }
            }

            await this.loadReview(review.id);
            this.notification.add("Performance Review saved successfully.", {
                type: "success",
            });
        } catch (error) {
            this.notification.add(
                error?.message || "Unable to save the Performance Review.",
                { type: "danger" }
            );
        } finally {
            this.state.saving = false;
        }
    }

    async saveWithoutLock() {
        const oldSaving = this.state.saving;
        this.state.saving = false;
        try {
            await this.save();
        } finally {
            this.state.saving = oldSaving;
        }
    }

    async submit(method, message) {
        if (!this.state.review || this.state.saving) {
            return;
        }

        this.state.saving = true;
        try {
            await this.saveWithoutLock();
            await this.orm.call("performance.review", method, [[this.state.review.id]]);
            this.notification.add(message, { type: "success" });
            await this.loadReviews();
        } catch (error) {
            this.notification.add(
                error?.message || "Unable to submit the Performance Review.",
                { type: "danger" }
            );
        } finally {
            this.state.saving = false;
        }
    }

    submitEmployee() {
        return this.submit(
            "action_submit_employee",
            "Performance Review submitted successfully."
        );
    }

    submitManager() {
        return this.submit(
            "action_submit_manager",
            "Manager Review submitted successfully."
        );
    }

    submitSecondManager() {
        return this.submit(
            "action_submit_second_manager",
            "Final Performance Review submitted successfully."
        );
    }

    getStatusLabel() {
        return {
            draft: "Employee Review",
            manager_review: "Manager Review",
            second_manager_review: "Second Manager Review",
            completed: "Completed",
            cancelled: "Cancelled",
        }[this.state.review?.state] || "";
    }

    getQuarter() {
        return this.state.review?.quarter
            ? this.state.review.quarter.toUpperCase()
            : "";
    }

    getCategoryKey(category) {
        const value = (category || "").toLowerCase().trim();
        if (value.includes("behaviour") || value.includes("behavior")) {
            return "behavioural";
        }
        if (value.includes("revenue")) {
            return "revenue";
        }
        if (value.includes("solution")) {
            return "solution";
        }
        if (value.includes("capability")) {
            return "capability";
        }
        return "other";
    }

    getCategoryTitle(category) {
        const titles = {
            behavioural: "Behavioural Aspects",
            revenue: "Revenue / Revenue Enablement",
            solution: "Solution / Solution Enablement",
            capability: "Capability / Capability Enablement",
        };
        const key = this.getCategoryKey(category);
        return titles[key] || category || "Performance Parameter";
    }

    getCategoryClass(category) {
        return `bxi-pr-category-${this.getCategoryKey(category)}`;
    }

    getGroupedLines() {
        const groups = [];
        const byKey = new Map();

        for (const line of [...this.state.lines].sort(
            (a, b) => (a.sequence || 0) - (b.sequence || 0) || a.id - b.id
        )) {
            const key = this.getCategoryKey(line.category);
            if (!byKey.has(key)) {
                const group = {
                    key,
                    title: this.getCategoryTitle(line.category),
                    cssClass: this.getCategoryClass(line.category),
                    lines: [],
                };
                byKey.set(key, group);
                groups.push(group);
            }
            byKey.get(key).lines.push(line);
        }
        return groups;
    }

    getLineTarget(line) {
        return line.target || line.description || "";
    }
    getScoreOptions(line) {
        const category = (line.category || "").toLowerCase().trim();

        // Revenue / Revenue Enablement
        if (category.includes("revenue")) {
            return [
                { value: "1", label: "1" },
                { value: "2", label: "2" },
            ];
        }

        // All other categories
        return [
            { value: "1", label: "1" },
            { value: "2", label: "2" },
            { value: "3", label: "3" },
            { value: "4", label: "4" },
            { value: "5", label: "5" },
        ];
    }

    getScore(line) {
            const score = Number(line.manager_score || 0);
            return score.toFixed(2);
        }

        getFinalScore() {
            const score = Number(this.state.review?.final_score || 0);
            return score.toFixed(2);
        }

        getCompanyLogoSrc() {
            if (!this.state.review?.company_logo) {
                return "";
            }
            return `data:image/png;base64,${this.state.review.company_logo}`;
        }
    }

registry.category("actions").add(
    "bxi_performance_review_screen",
    PerformanceReviewScreen
);
