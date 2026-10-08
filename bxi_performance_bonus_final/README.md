# BXI Performance Bonus Policy - Odoo 19 Community

This module is directly integrated with `bxi_performance_review_owl`.

## Dependencies

- base
- hr
- mail
- bxi_performance_review_owl

It does NOT depend on `hr_contract`, payroll, or enterprise modules.

## Existing Performance Review integration

The module reads:

`performance.review`

Fields used:
- employee_id
- period_id
- period_id.date_start
- period_id.date_end
- state
- calibration

Only completed Performance Reviews are used for quarterly calibration.

Quarter mapping for the policy's Apr-Mar annual cycle:
- Q1 = Apr-Jun
- Q2 = Jul-Sep
- Q3 = Oct-Dec
- Q4 = Jan-Mar

## Important policy interpretation

The supplied policy says the bonus depends on performance rating, company/unit performance and affordability, and that the annual aligned performance cycle is Apr-Mar. It does NOT provide:
- exact rating-to-payout percentages
- a formula to convert quarterly calibration ratings into an annual rating
- exact compensation field technical names
- a payroll/contract technical model

Therefore:
- target bonus % is configurable
- rating payout factors are configurable
- quarterly aggregation is configurable as Manual, Average, or Latest
- payroll-on-payday is confirmed by HR on each bonus line
- no `hr_contract` dependency is used

## Eligibility

HR maintains on employee:
- Performance Bonus in Compensation
- Bonus Employment Type
- Bonus Grade
- Bonus Geography
- Sales Incentive Employee
- Rebadged Employee
- Annual Bonus Salary Basis

An employee is eligible when the configured policy checks pass and a final calibration is available.

## Workflow

1. Configure employees' Bonus Policy fields.
2. Configure Bonus Plan and approved rating payout rules.
3. Create annual bonus cycle, normally 1 April to 31 March.
4. Click Generate Employees.
5. Click Refresh Performance Ratings.
6. Review Q1/Q2/Q3/Q4 calibration.
7. Select/confirm final calibration.
8. Confirm employee is on payroll on Bonus Pay Day.
9. Review eligibility and calculated bonus.
10. Approve.
11. Mark Paid after payment.

Bonus Pay Date is automatically cycle end + 60 days.

## Example rating payout rules

These are NOT policy values; configure your approved company values:

1.0-1.9 => 0.0
2.0-2.9 => 0.5
3.0-3.9 => 1.0
4.0-5.0 => 1.2

## No changes to OWL module

The bonus module only reads `performance.review` records. It does not modify the OWL module's workflow or fields.
