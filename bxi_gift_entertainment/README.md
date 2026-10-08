# BXI Gift and Entertainment Policy — Odoo 19 (Corrected)

This package is the corrected version of the uploaded BXI Gift & Entertainment implementation,
reviewed against the supplied policy.

## Corrections

- Receiving: USD 101–200 (Americas/ANZ/Europe) and USD >10–50 (other countries) are declarations,
  not L4 approvals. The module records declaration + LSO review separately.
- Receiving limits are cumulative per employee, per giver, per calendar year.
- Government official giving is capped at USD 50 within one year and requires L4+.
- Prize / award / raffle giving requires a BXI-approved marketing event/campaign.
- Donation approval is cumulative by financial year: <= USD 10,000 -> L1 + Ethics; >10,000 to
  USD 250,000 -> CEO + CFO; >250,000 is prohibited; single transaction max USD 50,000.
- Donation > USD 25 requires LSO due diligence; personal-capacity donations are not reimbursable.
- Donation routing defaults to reimbursement up to USD 3,000 and EdgeFi above USD 3,000. The supplied
  policy text has OCR ambiguity (`$J,000`), so this setting is configurable and must be confirmed
  against the signed policy.
- Business marketing sponsorship remains L1/MD permission and outside Ethics Committee.
- Charitable sponsorship requires Ethics Committee approval and LSO due diligence.
- Sponsorship solicitation requires L1/MD request, CEO+CFO approval and due diligence; >= USD 10,000
  adds Ethics Committee approval and LSO notification.
- Government attendees in sponsorship trigger L4 approval and government-official controls.
- Approval lines use explicit `res_model + res_id`; the fragile One2many/Many2oneReference relationship
  from the uploaded version has been removed.
- Missing approvers are configuration errors; the module no longer silently escalates to a different
  approval level.
- EdgeFi API calls are not fabricated. EdgeFi declaration/payment references are captured in Odoo.

## Policy points intentionally left configurable / requiring business confirmation

1. The India giving table starts at Rs. 50. The supplied policy does not explicitly state what happens
   below Rs. 50. The module retains the existing configured 0–500 approval row rather than inventing
   a new exemption.
2. The donation reimbursement/direct-payment threshold appears as `$J,000` in the supplied OCR.
   The module defaults this to USD 3,000 but exposes it in Settings for confirmation.
3. The signed policy should be used as the legal source of truth where OCR text is ambiguous.

## Dependencies

- `hr`
- `mail`
- `hr_expense`
- `bxi_hr_employee`

The BXI employee hierarchy dependency is retained because the uploaded module uses:
`role_band`, `l1_head_id`, `l2_head_id`, `l3_head_id`, `l4_head_id`.

## Installation

1. Copy `bxi_gift_entertainment` to the Odoo addons path.
2. Restart Odoo.
3. Update Apps List.
4. Upgrade/install the module.
5. Configure employee role bands and L1-L4 heads.
6. Configure MD/CEO/CFO/Board/LSO/Ethics Committee groups.
7. Verify the Policy Matrix and Settings in UAT.
8. Test boundary values and approval routing before production.
