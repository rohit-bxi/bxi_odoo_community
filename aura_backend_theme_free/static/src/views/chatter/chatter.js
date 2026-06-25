/** @odoo-module **/

const STORAGE_WIDTH_KEY = "tbt.chatter.width";
const MIN_WIDTH = 300;
const MAX_WIDTH = 680;

function clampWidth(value) {
    return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, value));
}

function applyWidth(container, width) {
    const next = clampWidth(width);
    container.style.width = `${next}px`;
    container.style.flex = `0 0 ${next}px`;
}

function ensureControls(container) {
    if (container.dataset.tbtChatterInit === "1") {
        return;
    }
    container.dataset.tbtChatterInit = "1";
    container.classList.add("tbt_chatter_container");

    const handle = document.createElement("div");
    handle.className = "tbt_chatter_resize_handle";

    handle.addEventListener("mousedown", (ev) => {
        ev.preventDefault();

        const startX = ev.clientX;
        const startWidth = container.getBoundingClientRect().width;

        const onMouseMove = (moveEv) => {
            const delta = startX - moveEv.clientX;
            applyWidth(container, startWidth + delta);
            localStorage.setItem(STORAGE_WIDTH_KEY, String(clampWidth(startWidth + delta)));
        };

        const onMouseUp = () => {
            document.removeEventListener("mousemove", onMouseMove);
            document.removeEventListener("mouseup", onMouseUp);
        };

        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
    });

    container.append(handle);

    const savedWidth = Number.parseInt(localStorage.getItem(STORAGE_WIDTH_KEY) || "", 10);
    if (Number.isFinite(savedWidth)) {
        applyWidth(container, savedWidth);
    }
}

function initializeAll() {
    document.querySelectorAll(".o-mail-ChatterContainer.o-mail-Form-chatter").forEach((container) => {
        if (!container.classList.contains("o-aside")) {
            return;
        }
        ensureControls(container);
    });
}

const observer = new MutationObserver(initializeAll);

let observerStarted = false;

function startObserver() {
    if (observerStarted) return;
    const target = document.body || document.documentElement;
    if (!target) return;
    observerStarted = true;
    initializeAll();
    observer.observe(target, { childList: true, subtree: true });
}

startObserver();
if (!observerStarted) {
    window.addEventListener("DOMContentLoaded", startObserver, { once: true });
}
