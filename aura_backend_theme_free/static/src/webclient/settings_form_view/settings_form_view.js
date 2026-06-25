// /** @odoo-module **/

// import { patch } from "@web/core/utils/patch";
// import { SettingsApp } from "@web/webclient/settings_form_view/settings/settings_app";
// import { SettingsPage } from "@web/webclient/settings_form_view/settings/settings_page";

// const SETTINGS_ICON_BY_MODULE = {
//     account: "/aura_backend_theme_free/static/src/img/accounting.svg",
//     account_accountant: "/aura_backend_theme_free/static/src/img/accounting.svg",
//     apps: "/aura_backend_theme_free/static/src/img/apps.svg",
//     base: "/aura_backend_theme_free/static/src/img/apps.svg",
//     calendar: "/aura_backend_theme_free/static/src/img/second_icons/calendar.svg",
//     contacts: "/aura_backend_theme_free/static/src/img/contacts.svg",
//     crm: "/aura_backend_theme_free/static/src/img/crm.svg",
//     discuss: "/aura_backend_theme_free/static/src/img/discuss.svg",
//     documents: "/aura_backend_theme_free/static/src/img/second_icons/documents.svg",
//     event: "/aura_backend_theme_free/static/src/img/second_icons/event.svg",
//     fleet: "/aura_backend_theme_free/static/src/img/second_icons/fleet.svg",
//     hr: "/aura_backend_theme_free/static/src/img/hr.svg",
//     hr_attendance: "/aura_backend_theme_free/static/src/img/second_icons/hr_attendance.svg",
//     hr_expense: "/aura_backend_theme_free/static/src/img/second_icons/hr_expense.svg",
//     hr_holidays: "/aura_backend_theme_free/static/src/img/second_icons/hr_holidays.svg",
//     hr_recruitment: "/aura_backend_theme_free/static/src/img/second_icons/hr_recruitment.svg",
//     inventory: "/aura_backend_theme_free/static/src/img/inventory.svg",
//     invoicing: "/aura_backend_theme_free/static/src/img/accounting.svg",
//     knowledge: "/aura_backend_theme_free/static/src/img/second_icons/knowledge.svg",
//     maintenance: "/aura_backend_theme_free/static/src/img/second_icons/maintenance.svg",
//     mail: "/aura_backend_theme_free/static/src/img/second_icons/mail.svg",
//     marketing_automation: "/aura_backend_theme_free/static/src/img/second_icons/marketing_automation.svg",
//     mass_mailing: "/aura_backend_theme_free/static/src/img/second_icons/mass_mailing.svg",
//     mrp: "/aura_backend_theme_free/static/src/img/second_icons/mrp.svg",
//     planning: "/aura_backend_theme_free/static/src/img/second_icons/planning.svg",
//     point_of_sale: "/aura_backend_theme_free/static/src/img/second_icons/point_of_sale.svg",
//     pos_sale: "/aura_backend_theme_free/static/src/img/second_icons/point_of_sale.svg",
//     project: "/aura_backend_theme_free/static/src/img/project.svg",
//     purchase: "/aura_backend_theme_free/static/src/img/purchase.svg",
//     quality: "/aura_backend_theme_free/static/src/img/second_icons/quality.svg",
//     quality_control: "/aura_backend_theme_free/static/src/img/second_icons/quality.svg",
//     repair: "/aura_backend_theme_free/static/src/img/second_icons/repair.svg",
//     sale: "/aura_backend_theme_free/static/src/img/second_icons/sale.svg",
//     sales: "/aura_backend_theme_free/static/src/img/sales.svg",
//     settings: "/aura_backend_theme_free/static/src/img/settings.svg",
//     social: "/aura_backend_theme_free/static/src/img/second_icons/social.svg",
//     spreadsheet_dashboard: "/aura_backend_theme_free/static/src/img/second_icons/spreadsheet_dashboard.svg",
//     stock: "/aura_backend_theme_free/static/src/img/second_icons/stock.svg",
//     survey: "/aura_backend_theme_free/static/src/img/second_icons/survey.svg",
//     website: "/aura_backend_theme_free/static/src/img/second_icons/website.svg",
// };

// function resolveSettingsIcon(moduleKey, fallback) {
//     const key = (moduleKey || "").toLowerCase();
//     return SETTINGS_ICON_BY_MODULE[key] || fallback;
// }

// patch(SettingsPage.prototype, {
//     getModuleIconUrl(module) {
//         return resolveSettingsIcon(module?.key, module?.imgurl);
//     },
// });

// patch(SettingsApp.prototype, {
//     getAppIconUrl() {
//         return resolveSettingsIcon(this.props?.key, this.props?.imgurl);
//     },
// });
