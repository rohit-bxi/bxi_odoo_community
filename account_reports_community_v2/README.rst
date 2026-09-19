=============================================
Advanced Financial Reports for Odoo Community
=============================================

Professional financial reporting for Odoo Community Edition.

This module provides a complete set of essential accounting reports using Odoo Community's native reporting framework, including ``account.report``, ``account.report.line``, and ``account.report.expression``.

The implementation is designed from the ground up for Odoo Community users and does not depend on Odoo Enterprise's proprietary ``account_reports`` module.

Features
========

Financial Reports
-----------------
* Trial Balance
* General Ledger
* Balance Sheet
* Profit and Loss
* Partner Ledger
* Aged Receivable
* Aged Payable
* Tax Report
* Journal Report
* Cash Flow Statement

Reporting Capabilities
----------------------
* Interactive reports in the Odoo interface
* Drill-down from report lines to accounting details
* Flexible reporting periods
* Period comparison
* Report-specific filters
* Multi-company reporting
* Multi-currency support
* PDF export
* XLSX export
* Pagination for large transaction datasets

Built for Odoo Community
========================

This project is intended for Odoo Community Edition.

It provides an independent implementation of financial reporting functionality using the accounting reporting framework available in Odoo Community.

**Important:** This module does not depend on, include, or reuse proprietary code from Odoo Enterprise's ``account_reports`` module. The reporting functionality is implemented independently for Odoo Community.

Requirements
============

* Odoo 19.0 Community Edition
* Standard Odoo account module

No Odoo Enterprise modules are required.

Installation
============

1. Download or clone this repository.
2. Copy the ``account_reports_community_v2`` directory into your Odoo addons path.
3. Restart the Odoo server.
4. Update the Apps list.
5. Search for Advanced Financial Reports for Odoo Community.
6. Install the module.

The module depends only on the standard Odoo account module.

Usage
=====

After installation, open:

**Accounting → Reporting**

The available financial reports can be accessed from the reporting menu.

Reports can be viewed directly in Odoo and exported to PDF or XLSX.

Report Overview
===============

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Report
     - Purpose
   * - Trial Balance
     - Review debit and credit balances across accounts
   * - General Ledger
     - Analyze account movements and journal entries
   * - Balance Sheet
     - Review assets, liabilities, and equity
   * - Profit and Loss
     - Analyze revenue, expenses, and profitability
   * - Partner Ledger
     - Review customer and vendor accounting activity
   * - Aged Receivable
     - Analyze outstanding customer receivables
   * - Aged Payable
     - Analyze outstanding supplier payables
   * - Tax Report
     - Review tax-related accounting information
   * - Journal Report
     - Analyze accounting activity by journal
   * - Cash Flow Statement
     - Analyze cash movement and financial cash flows

Project Structure
=================

.. code-block:: text

   account_reports_community_v2/
   ├── data/
   ├── models/
   ├── report/
   ├── static/
   ├── tests/
   ├── views/
   ├── __init__.py
   └── __manifest__.py

Testing
=======

The module includes automated tests covering important reporting functionality, including:

* Financial report calculations
* General Ledger
* Trial Balance
* Profit and Loss
* Balance Sheet
* Partner Ledger
* Aged Receivable
* Aged Payable
* Tax reporting
* Journal reporting
* Cash Flow
* Multi-currency scenarios
* Report exports
* Reporting expressions and engines

Compatibility
=============

.. list-table::
   :widths: 50 50
   :header-rows: 1

   * - Odoo Version
     - Community
   * - Odoo 19.0
     - Yes

License
=======

This project is licensed under the LGPL-3 license.

See the LICENSE file for the full license text.

Author
======

**Ajith**

Odoo Technical Developer

**Website:** https://ajithkalidasan.github.io/ajith/

Support
=======

If you find a bug, have a feature request, or need help with the module, please open an issue in the project repository or contact the author.

---

**Advanced Financial Reports for Odoo Community**

Professional financial reporting, built for Community Edition.