/* ─── Country → State binding ─────────────────────────────────────────────── */
function initStateBinding() {
    function bind(countryId, stateId) {
        var country = document.getElementById(countryId);
        var state   = document.getElementById(stateId);
        if (!country || !state) return;

        country.addEventListener('change', function () {
            fetch('/my/submit-travel-request?country_id=' + this.value)
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    state.innerHTML = '<option value="">Select State</option>';
                    data.states.forEach(function (s) {
                        var opt  = document.createElement('option');
                        opt.value = s.id;
                        opt.text  = s.name;
                        state.appendChild(opt);
                    });
                });
        });
    }

    bind('from_country', 'from_state');
    bind('to_country',   'to_state');
}
setTimeout(initStateBinding, 500);


/* ─── Approve / Reject confirmation modal ────────────────────────────────── */
/* Uses manual class toggling — no dependency on the Bootstrap global object  */
(function () {
    var APPROVE_COLOR = '#198754';
    var REJECT_COLOR  = '#dc3545';

    /* ── Helpers ── */
    function showModal() {
        var modal = document.getElementById('trActionModal');
        if (!modal) return;
        modal.style.display = 'block';
        modal.removeAttribute('aria-hidden');
        modal.setAttribute('aria-modal', 'true');
        modal.classList.add('show');

        // backdrop
        var bd = document.createElement('div');
        bd.id = 'trModalBackdrop';
        bd.className = 'modal-backdrop fade show';
        document.body.appendChild(bd);
        document.body.classList.add('modal-open');
    }

    function hideModal() {
        var modal = document.getElementById('trActionModal');
        if (!modal) return;
        modal.style.display = 'none';
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
        modal.removeAttribute('aria-modal');

        var bd = document.getElementById('trModalBackdrop');
        if (bd) bd.remove();
        document.body.classList.remove('modal-open');
    }

    /* ── Wire everything on DOM ready ── */
    function init() {
        var modal = document.getElementById('trActionModal');
        if (!modal) return;

        var modalHeader = document.getElementById('trModalHeader');
        var modalIcon   = document.getElementById('trModalIcon');
        var modalTitle  = document.getElementById('trActionModalLabel');
        var modalRef    = document.getElementById('trModalRef');
        var modalMsg    = document.getElementById('trModalMsg');
        var actionForm  = document.getElementById('trActionForm');
        var recIdInput  = document.getElementById('trActionRecId');
        var confirmBtn  = document.getElementById('trModalConfirmBtn');

        /* Action buttons → open modal */
        document.querySelectorAll('.tr-action-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var type  = btn.dataset.type;
                var recId = btn.dataset.recId;
                var ref   = btn.dataset.ref || ('Request #' + recId);

                actionForm.action = '/my/travel-request/' + type;
                recIdInput.value  = recId;
                modalRef.textContent = ref;

                if (type === 'approve') {
                    modalHeader.style.background = APPROVE_COLOR;
                    modalIcon.className   = 'fa fa-check-circle fa-lg me-2';
                    modalTitle.textContent = 'Approve Travel Request';
                    modalMsg.textContent   = 'Are you sure you want to approve this request? It will be forwarded to HR for further processing.';
                    confirmBtn.style.background = APPROVE_COLOR;
                    confirmBtn.textContent = 'Yes, Approve';
                } else {
                    modalHeader.style.background = REJECT_COLOR;
                    modalIcon.className   = 'fa fa-times-circle fa-lg me-2';
                    modalTitle.textContent = 'Reject Travel Request';
                    modalMsg.textContent   = 'Are you sure you want to reject this request? This action will cancel it.';
                    confirmBtn.style.background = REJECT_COLOR;
                    confirmBtn.textContent = 'Yes, Reject';
                }

                showModal();
            });
        });

        /* Close buttons → hide modal */
        modal.querySelectorAll('[data-bs-dismiss="modal"]').forEach(function (el) {
            el.addEventListener('click', hideModal);
        });

        /* Click outside modal-dialog → close */
        modal.addEventListener('click', function (e) {
            if (e.target === modal) hideModal();
        });

        /* ESC key → close */
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') hideModal();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());