/** @odoo-module **/

function applyLoadingStyleClass() {
    const root = document.documentElement;
    if (!root) {
        return;
    }
    const styleToken = getComputedStyle(root)
        .getPropertyValue('--tbt-loading-style-dynamic')
        .trim() || 'arc';

    const allowed = new Set(['arc', 'dual_arc', 'spinner', 'sun', 'dots', 'quad']);
    const style = allowed.has(styleToken) ? styleToken : 'arc';

    root.classList.remove(
        'tbt-loading-style-arc',
        'tbt-loading-style-dual_arc',
        'tbt-loading-style-spinner',
        'tbt-loading-style-sun',
        'tbt-loading-style-dots',
        'tbt-loading-style-quad'
    );
    root.classList.add(`tbt-loading-style-${style}`);
}

function syncLoadingActiveClass() {
    const root = document.documentElement;
    if (!root) {
        return;
    }
    const el = document.querySelector('.o_loading_indicator');
    const isVisible = !!el && getComputedStyle(el).display !== 'none';
    root.classList.toggle('tbt-loading-active', isVisible);
}

function initLoadingObserver() {
    const observer = new MutationObserver(() => {
        syncLoadingActiveClass();
    });
    observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class', 'style'],
    });
    syncLoadingActiveClass();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        applyLoadingStyleClass();
        initLoadingObserver();
    }, { once: true });
} else {
    applyLoadingStyleClass();
    initLoadingObserver();
}
