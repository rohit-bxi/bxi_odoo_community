/** @odoo-module **/
/**
 * Aura Backend Theme - Free — NavBar patch
 *
 * Adds to the stock Odoo NavBar:
 *   1. Mobile off-canvas drawer  (hamburger open/close + backdrop)
 *   2. Sidebar quick links        (apps, settings, profile)
 *   3. Top sub-menu strip        (current app sections)
 *
 * All state is local to the component — no Odoo models required.
 */

import { patch }      from '@web/core/utils/patch';
import { browser }    from '@web/core/browser/browser';
import { user }       from '@web/core/user';
import { NavBar }     from '@web/webclient/navbar/navbar';
import {
    onMounted,
    onPatched,
    onWillUnmount,
    useRef,
    useState,
} from '@odoo/owl';

// ─── Apps that should NOT show a sub-nav tree in the sidebar ─────────────────
const NO_SUBNAV_XMLIDS = new Set([
    'spreadsheet_dashboard.spreadsheet_dashboard_menu_root',
]);

function buildMenuHref(menu) {
    if (!menu || (!menu.actionPath && !menu.actionID)) return '';
    return `/odoo/${menu.actionPath || `action-${menu.actionID}`}`;
}

function findMenuPathById(tree, targetId, acc = []) {
    if (!tree) return null;
    const next = [...acc, tree];
    if (tree.id === targetId) {
        return next;
    }
    for (const child of tree.childrenTree || []) {
        const found = findMenuPathById(child, targetId, next);
        if (found) {
            return found;
        }
    }
    return null;
}

// ─────────────────────────────────────────────────────────────────────────────
patch(NavBar.prototype, {
    setup() {
        super.setup();

        this.menuService   = this.env.services.menu;
        this.actionService = this.env.services.action;
        this.tbtUser = user;

        // ── 1. Mobile off-canvas sidebar ─────────────────────────────────────
        this.mobileSidebarState = useState({ isOpen: false });
        this.toggleMobileSidebar = () => {
            this.mobileSidebarState.isOpen = !this.mobileSidebarState.isOpen;
        };
        this.closeMobileSidebar = () => {
            this.mobileSidebarState.isOpen = false;
        };

        // ── 2. Top submenu strip ──────────────────────────────────────────────
        this.topSubmenuState = useState({ openSectionId: null, openSubItemId: null, panelLeft: 0 });
        this.topSubmenuRef = useRef('topSubmenu');
        this.isTopSectionOpen = (sectionId) =>
            this.topSubmenuState.openSectionId === sectionId;
        this.getOpenTopSection = () =>
            this.currentAppSections.find(s => s.id === this.topSubmenuState.openSectionId) || null;
        this.toggleTopSection = (section, ev) => {
            const nextId = section?.id;
            const closing = this.topSubmenuState.openSectionId === nextId;
            this.topSubmenuState.openSectionId = closing ? null : nextId;
            this.topSubmenuState.openSubItemId = null;
            if (!closing && ev?.currentTarget) {
                const bar = this.topSubmenuRef.el;
                const btn = ev.currentTarget;
                const barRect = bar.getBoundingClientRect();
                const btnRect = btn.getBoundingClientRect();
                this.topSubmenuState.panelLeft = btnRect.left - barRect.left;
            }
        };
        this.isSubItemOpen = (itemId) =>
            this.topSubmenuState.openSubItemId === itemId;
        this.toggleSubItem = (item) => {
            const nextId = item?.id;
            this.topSubmenuState.openSubItemId =
                this.topSubmenuState.openSubItemId === nextId ? null : nextId;
        };
        this.onTopSubmenuItemSelection = (menu) => {
            this.topSubmenuState.openSectionId = null;
            this.topSubmenuState.openSubItemId = null;
            this.onNavBarDropdownItemSelection(menu);
        };
        this.onTopSectionLeafClick = (section) => {
            this.topSubmenuState.openSectionId = null;
            this.topSubmenuState.openSubItemId = null;
            this.onNavBarDropdownItemSelection(section);
        };

        // ── 3. Logo / company helpers ─────────────────────────────────────────
        this.getCompanyLogo = () => {
            const id = this.currentCompany?.id || '';
            return `/web/binary/company_logo?company=${id}`;
        };
        this.getUserAvatarUrl = () => {
            const userId = this.tbtUser?.userId;
            return userId
                ? `/web/image?model=res.users&id=${userId}&field=avatar_128`
                : '/web/static/img/default_icon_app.png';
        };
        this.onLogoClick = () => {
            browser.location.href = '/odoo/dashboards';
        };
        this.openMyProfile = () => {
            this.actionService.doAction('base.action_res_users_my');
        };

        this.getTopbarAppName = () => {
            const app = this.currentApp;
            return app?.name || '';
        };

        // ── 4. App helpers ────────────────────────────────────────────────────
        this.isAppWithoutSubnav = () =>
            NO_SUBNAV_XMLIDS.has(this.currentApp?.xmlid);

        this.getApps = () => {
            return this.menuService.getApps().filter(a =>
                a.xmlid !== 'base.menu_administration' &&
                a.xmlid !== 'base.menu_management'
            );
        };
        this.getSettingsApp = () =>
            this.menuService.getApps()
                .find(a => a.xmlid === 'base.menu_administration' || a.name === 'Settings');
        this.getAppsApp = () =>
            this.menuService.getApps()
                .find(a =>
                    a.xmlid === 'base.menu_management' ||
                    a.xmlid === 'base.menu_apps' ||
                    a.name === 'Apps'
                );

        this.openAppsMenu = () => {
            const apps = this.getAppsApp();
            if (apps) {
                this.onNavBarDropdownItemSelection(apps);
                return;
            }
            browser.location.href = '/odoo/apps/modules';
        };

        this.openSettingsMenu = () => {
            const settings = this.getSettingsApp();
            if (settings) {
                this.onNavBarDropdownItemSelection(settings);
                return;
            }
            browser.location.href = '/odoo/settings';
        };

        // Resolve an app's icon using Odoo's built-in webIconData
        this.getAppIcon = (app) => {
            if (!app) return '/web/static/img/default_icon_app.png';
            const data = app.webIconData;
            if (data) {
                if (data.startsWith('data:image') || data.startsWith('/')) return data;
                const prefix = data.startsWith('P')
                    ? 'data:image/svg+xml;base64,'
                    : 'data:image/png;base64,';
                return prefix + data.replace(/\s/g, '');
            }
            return '/web/static/img/default_icon_app.png';
        };

        // ── 5. Overflow tracking for the sidebar scroll area ──────────────────
        this.sidebarScrollRef  = useRef('sidebarScroll');
        this._updateOverflow   = () => {
            const el = this.sidebarScrollRef?.el;
            if (!el) return;
            el.parentElement?.classList.toggle(
                'tbt_sidebar_overflowing',
                el.scrollHeight > el.clientHeight + 1
            );
        };

        // Close top submenu on outside click or Escape
        this._onDocumentClick = (ev) => {
            const submenu = this.topSubmenuRef?.el;
            if (this.topSubmenuState.openSectionId && submenu && !submenu.contains(ev.target)) {
                this.topSubmenuState.openSectionId = null;
            }
        };
        this._onDocumentKeydown = (ev) => {
            if (ev.key === 'Escape' && this.topSubmenuState.openSectionId) {
                this.topSubmenuState.openSectionId = null;
            }
        };

        // ── Lifecycle ──────────────────────────────────────────────────────────
        onMounted(() => {
            this._updateOverflow();
            document.addEventListener('click',   this._onDocumentClick);
            document.addEventListener('keydown', this._onDocumentKeydown);
            window.addEventListener('resize',    this._updateOverflow);
        });
        onPatched(() => {
            this._updateOverflow();
            if (this.topSubmenuState.openSectionId && !this.getOpenTopSection()) {
                this.topSubmenuState.openSectionId = null;
            }
        });
        onWillUnmount(() => {
            document.removeEventListener('click',   this._onDocumentClick);
            document.removeEventListener('keydown', this._onDocumentKeydown);
            window.removeEventListener('resize',    this._updateOverflow);
        });
    },

    // ── Computed ───────────────────────────────────────────────────────────────

    get currentCompany() {
        return user.activeCompany;
    },
});
