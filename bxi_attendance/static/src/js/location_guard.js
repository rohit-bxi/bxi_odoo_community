    odoo.define('bxi_attendance.location_guard', function (require) {
    'use strict';

    const { useService } = require('web.core.utils');
    const { useDebounced } = require('web.core.utils.timing');

    const checkLocationPermission = () => new Promise((resolve, reject) => {
        if (!navigator || !navigator.geolocation) {
            reject(new Error('Please enable location access in Chrome or your browser before checking in or checking out.'));
            return;
        }

        navigator.geolocation.getCurrentPosition(
            ({ coords }) => {
                if (!coords || coords.latitude === undefined || coords.longitude === undefined) {
                    reject(new Error('Please enable location access in Chrome or your browser before checking in or checking out.'));
                    return;
                }
                resolve({ latitude: coords.latitude, longitude: coords.longitude });
            },
            () => {
                reject(new Error('Please enable location access in Chrome or your browser before checking in or checking out.'));
            },
            { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
        );
    });

    const patchCheckInOut = () => {
        const checkInOutButtons = document.querySelectorAll('button.o_hr_attendance_sign_in_out_icon');
        checkInOutButtons.forEach((button) => {
            if (button.dataset.bxiLocationGuardBound === 'true') {
                return;
            }
            button.dataset.bxiLocationGuardBound = 'true';
            const originalClick = button.onclick;
            button.onclick = async function (event) {
                try {
                    const coords = await checkLocationPermission();
                    if (originalClick) {
                        const result = originalClick.call(this, event);
                        if (result && typeof result.then === 'function') {
                            await result;
                        }
                    }
                    const hiddenPosition = document.createElement('input');
                    hiddenPosition.type = 'hidden';
                    hiddenPosition.name = 'attendance_location';
                    hiddenPosition.value = JSON.stringify(coords);
                    document.body.appendChild(hiddenPosition);
                    return true;
                } catch (error) {
                    if (error && error.message) {
                        alert(error.message);
                    }
                    return false;
                }
            };
        });
    };

    document.addEventListener('DOMContentLoaded', patchCheckInOut);
    const observer = new MutationObserver(() => patchCheckInOut());
    observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
    return {};
});
