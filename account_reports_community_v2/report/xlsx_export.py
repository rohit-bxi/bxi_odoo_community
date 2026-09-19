import io


def build_xlsx(report, data):
    """Builds an XLSX workbook (as raw bytes) from a report's already-computed
    data dict (the same envelope action_get_report_data returns, but always
    called with options['export_mode']=True so every foldable row is fully
    expanded and no aml_rows list is truncated - see the export_mode comment
    in account_report_engine.py).

    Dispatches on report_handler since each bespoke handler's row shape is
    different (a generic expression-tree hierarchy vs. a flat list of
    account/partner/tax/journal groups with nested journal-item rows) -
    mirrors the dispatch in account.report._get_report_data / the frontend's
    per-handler table templates.
    """
    import xlsxwriter  # noqa: PLC0415 (lazy import, matches web/controllers/pivot.py)

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet(_safe_sheet_name(report.name))

    formats = {
        'title': workbook.add_format({'bold': True, 'font_size': 14}),
        'subtitle': workbook.add_format({'italic': True, 'font_color': '#666666'}),
        'header': workbook.add_format({'bold': True, 'bg_color': '#DDDDDD', 'border': 1}),
        'bold': workbook.add_format({'bold': True}),
        'bold_amount': workbook.add_format({'bold': True, 'num_format': '#,##0.00'}),
        'amount': workbook.add_format({'num_format': '#,##0.00'}),
        'date': workbook.add_format({'num_format': 'yyyy-mm-dd'}),
        'level0': workbook.add_format({'bold': True}),
        'level1': workbook.add_format({'indent': 1}),
        'level2': workbook.add_format({'indent': 2}),
        'level3': workbook.add_format({'indent': 3}),
    }

    worksheet.write(0, 0, report.name, formats['title'])
    options = data.get('options') or {}
    period_desc = f"{options.get('date_from', '')} → {options.get('date_to', '')}"
    worksheet.write(1, 0, period_desc, formats['subtitle'])

    handler = data.get('report_handler') or 'generic'
    row = 3
    if handler == 'generic':
        row = _write_generic(worksheet, formats, data, row)
    elif handler in ('general_ledger', 'partner_ledger', 'journal_report'):
        row = _write_ledger_style(worksheet, formats, data, row, handler)
    elif handler == 'aged_partner_balance':
        row = _write_aged_balance(worksheet, formats, data, row)
    elif handler == 'tax_report':
        row = _write_tax_report(worksheet, formats, data, row)

    worksheet.freeze_panes(4, 1)
    workbook.close()
    return output.getvalue()


def _safe_sheet_name(name):
    # Excel sheet names: max 31 chars, no []:*?/\
    cleaned = ''.join(c for c in (name or 'Report') if c not in '[]:*?/\\')
    return cleaned[:31] or 'Report'


def _level_format(formats, level):
    return formats.get(f'level{min(level, 3)}', formats['level3'])


def _write_generic(worksheet, formats, data, row):
    columns = data.get('columns') or []
    periods = data.get('periods') or []
    col = 1
    if len(periods) > 1:
        for period in periods:
            worksheet.merge_range(row, col, row, col + len(columns) - 1, period['label'], formats['header'])
            col += len(columns)
        row += 1

    worksheet.write(row, 0, 'Name', formats['header'])
    col = 1
    for _period in periods:
        for column in columns:
            worksheet.write(row, col, column['name'], formats['header'])
            col += 1
    row += 1

    def write_lines(lines, level):
        nonlocal row
        for line in lines:
            fmt = _level_format(formats, level)
            worksheet.write(row, 0, line.get('name') or '', fmt)
            col = 1
            for period in line.get('periods') or []:
                for pcol in period.get('columns') or []:
                    value = pcol.get('value')
                    amount_fmt = formats['bold_amount'] if level == 0 else formats['amount']
                    if value is not None:
                        worksheet.write_number(row, col, value, amount_fmt)
                    col += 1
            row += 1
            if line.get('children'):
                write_lines(line['children'], level + 1)

    write_lines(data.get('lines') or [], 0)
    worksheet.set_column(0, 0, 45)
    worksheet.set_column(1, max(1, len(columns) * max(1, len(periods))), 16)
    return row


_LEDGER_STYLE_HEADERS = {
    'general_ledger': ['Date', 'Journal Entry', 'Partner', 'Label', 'Debit', 'Credit', 'Balance'],
    'partner_ledger': ['Date', 'Journal Entry', 'Account', 'Label', 'Debit', 'Credit', 'Balance'],
    'journal_report': ['Date', 'Journal Entry', 'Account', 'Partner', 'Label', 'Debit', 'Credit'],
}
_LEDGER_STYLE_ROW_KEYS = {
    'general_ledger': ['date', 'move_name', 'partner', 'label', 'debit', 'credit', 'running_balance'],
    'partner_ledger': ['date', 'move_name', 'account', 'label', 'debit', 'credit', 'running_balance'],
    'journal_report': ['date', 'move_name', 'account', 'partner', 'label', 'debit', 'credit'],
}


def _write_ledger_style(worksheet, formats, data, row, handler):
    headers = _LEDGER_STYLE_HEADERS[handler]
    row_keys = _LEDGER_STYLE_ROW_KEYS[handler]
    amount_cols = {i for i, key in enumerate(row_keys) if key in ('debit', 'credit', 'running_balance')}

    for col, title in enumerate(headers):
        worksheet.write(row, col, title, formats['header'])
    row += 1

    for group in data.get('lines') or []:
        worksheet.write(row, 0, group.get('name') or '', formats['bold'])
        if 'opening_balance' in group:
            worksheet.write_number(row, len(headers) - 1, group['opening_balance'], formats['bold_amount'])
        row += 1

        for aml in group.get('aml_rows') or []:
            for col, key in enumerate(row_keys):
                value = aml.get(key)
                if value is None:
                    continue
                if col in amount_cols:
                    worksheet.write_number(row, col, value, formats['amount'])
                else:
                    worksheet.write(row, col, value)
            row += 1

        if 'closing_balance' in group:
            worksheet.write(row, 0, 'Closing Balance', formats['bold'])
            worksheet.write_number(row, len(headers) - 1, group['closing_balance'], formats['bold_amount'])
            row += 1
        elif handler == 'journal_report':
            worksheet.write(row, 0, 'Total', formats['bold'])
            worksheet.write_number(row, len(headers) - 2, group.get('total_debit', 0.0), formats['bold_amount'])
            worksheet.write_number(row, len(headers) - 1, group.get('total_credit', 0.0), formats['bold_amount'])
            row += 1
        row += 1

    for col, _title in enumerate(headers):
        worksheet.set_column(col, col, 30 if col in (1, 3) else 16)
    return row


def _write_aged_balance(worksheet, formats, data, row):
    bucket_columns = data.get('bucket_columns') or []
    headers = ['Partner'] + [b['label'] for b in bucket_columns] + ['Total']
    for col, title in enumerate(headers):
        worksheet.write(row, col, title, formats['header'])
    row += 1

    for line in data.get('lines') or []:
        worksheet.write(row, 0, line.get('name') or '', formats['bold'])
        col = 1
        for bucket in bucket_columns:
            worksheet.write_number(row, col, line.get('buckets', {}).get(bucket['key'], 0.0), formats['bold_amount'])
            col += 1
        worksheet.write_number(row, col, line.get('total', 0.0), formats['bold_amount'])
        row += 1

        for aml in line.get('aml_rows') or []:
            worksheet.write(row, 0, aml.get('label') or aml.get('move_name') or '', formats['level1'])
            worksheet.write(row, 1, aml.get('due_date') or '')
            worksheet.write_number(row, 2, aml.get('amount', 0.0), formats['amount'])
            row += 1
        row += 1

    worksheet.set_column(0, 0, 35)
    worksheet.set_column(1, len(headers) - 1, 16)
    return row


def _write_tax_report(worksheet, formats, data, row):
    headers = ['Tax', 'Base Amount', 'Tax Amount']
    for col, title in enumerate(headers):
        worksheet.write(row, col, title, formats['header'])
    row += 1

    for line in data.get('lines') or []:
        worksheet.write(row, 0, line.get('name') or '', formats['bold'])
        worksheet.write_number(row, 1, line.get('base_amount', 0.0), formats['bold_amount'])
        worksheet.write_number(row, 2, line.get('tax_amount', 0.0), formats['bold_amount'])
        row += 1

        for aml in line.get('aml_rows') or []:
            worksheet.write(row, 0, f"{aml.get('date', '')} - {aml.get('partner', '')}", formats['level1'])
            worksheet.write_number(row, 1, aml.get('base_amount', 0.0), formats['amount'])
            worksheet.write_number(row, 2, aml.get('tax_amount', 0.0), formats['amount'])
            row += 1
        row += 1

    worksheet.set_column(0, 0, 40)
    worksheet.set_column(1, 2, 16)
    return row
