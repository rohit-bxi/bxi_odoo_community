/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PerformanceReviewScreen extends Component {
    static template = "bxi_performance_review_owl.PerformanceReviewScreen";

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            filter: "my",
            reviews: [],
            review: null,
            lines: [],
            appraiseeQuestions: [],
            managerQuestions: [],
            currentUserId: null,
            error: null,
        });
        onWillStart(() => this.loadReviews());
    }

    async loadReviews() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const uid = await this.orm.call("performance.review", "get_current_user_id", []);
            this.state.currentUserId = uid;
            const domain = this.state.filter === "approve"
                ? ["|", ["manager_user_id", "=", uid], ["second_manager_user_id", "=", uid]]
                : [["employee_user_id", "=", uid]];

            this.state.reviews = await this.orm.searchRead(
                "performance.review",
                domain,
                ["id", "name", "employee_id", "period_id", "state", "year", "quarter", "final_score"],
                { order: "id desc", limit: 100 }
            );

            if (this.state.reviews.length) {
                const currentId = this.state.review && this.state.reviews.some(
                    (review) => review.id === this.state.review.id
                ) ? this.state.review.id : this.state.reviews[0].id;
                await this.loadReview(currentId);
            } else {
                this.clearReview();
            }
        } catch (error) {
            this.state.error = error?.message || "Unable to load Performance Reviews.";
            this.clearReview();
        } finally {
            this.state.loading = false;
        }
    }

    clearReview() {
        this.state.review = null;
        this.state.lines = [];
        this.state.appraiseeQuestions = [];
        this.state.managerQuestions = [];
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
                "can_edit_second", "can_edit_hr",
            ]
        );

        if (!result.length) {
            this.clearReview();
            return;
        }

        this.state.review = result[0];

        this.state.lines = await this.orm.searchRead(
            "performance.review.line",
            [["review_id", "=", id]],
            [
                "id", "sequence", "category", "weightage", "target",
                "description", "self_achievement", "manager_review", "manager_score",
            ],
            { order: "sequence asc, id asc" }
        );

        const questions = await this.orm.searchRead(
            "performance.review.question",
            [["review_id", "=", id]],
            ["id", "sequence", "question_type", "question", "response_type", "answer", "rating_scale", "appraisee_rating"],
            { order: "question_type, sequence, id" }
        );

        this.state.appraiseeQuestions = questions.filter(
            (q) => q.question_type === "appraisee"
        );
        this.state.managerQuestions = questions.filter(
            (q) => q.question_type === "manager"
        );
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

    canSeeManagerQuestions() {
        // This OWL dashboard is intentionally READONLY.
        // If the employee can open the review, the employee can see the
        // complete review, including manager/RM questions and answers.
        return Boolean(this.state.review);
    }

    getStarDisplay(item) {
        if (!item || item.question_type !== "appraisee" || !["rating", "both"].includes(item.response_type)) {
            return "";
        }

        const maxStars = Math.min(5, Math.max(1, Number(item.rating_scale || 5)));
        const rating = Math.min(
            maxStars,
            Math.max(0, Number(item.appraisee_rating || 0))
        );

        return "★".repeat(rating) + "☆".repeat(maxStars - rating);
    }

    getRatingText(item) {
        if (!item || item.question_type !== "appraisee" || !["rating", "both"].includes(item.response_type) || !item.appraisee_rating) {
            return "Not rated";
        }

        const maxStars = Math.min(5, Math.max(1, Number(item.rating_scale || 5)));
        return `${item.appraisee_rating}/${maxStars}`;
    }

    getStatusLabel() {
        return {
            draft: "Employee Review",
            manager_review: "Manager Review",
            second_manager_review: "Second Level Review",
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
        if (value.includes("behaviour") || value.includes("behavior")) return "behavioural";
        if (value.includes("revenue")) return "revenue";
        if (value.includes("solution")) return "solution";
        if (value.includes("capability")) return "capability";
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

    getScoreDisplay(line) {
        return line.manager_score || "-";
    }

    getCalibrationLabel(value) {
        return {
            "5": "Outstanding",
            "4": "Exceeds Expectations",
            "3": "Meets Expectations",
            "2": "Needs Improvement",
            "1": "Unsatisfactory",
        }[String(value || "")] || "-";
    }

    getFinalScore() {
        const score = Number(this.state.review?.final_score || 0);
        return score.toFixed(2);
    }

    getCompanyLogoSrc() {
        if (!this.state.review?.company_logo) return "";
        return `data:image/png;base64,${this.state.review.company_logo}`;
    }
}

registry.category("actions").add(
    "bxi_performance_review_screen",
    PerformanceReviewScreen
);
