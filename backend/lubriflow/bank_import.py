"""Validated CSV statement imports and conservative reconciliation suggestions."""
import csv
import hashlib
import io
import json
import re
from copy import deepcopy
from datetime import date, datetime
from .domain import require, dec, amount, identifier, get, RuleError
from .finance import finance_action, active_ledger


DEFAULT_MAPPING = dict(date='date', reference='reference', money_in='money_in', money_out='money_out',
                       description='description', balance='balance', delimiter=',', dateFormat='YYYY-MM-DD',
                       decimalSeparator='.', thousandsSeparator='')
DATE_FORMATS = {'YYYY-MM-DD': '%Y-%m-%d', 'DD/MM/YYYY': '%d/%m/%Y', 'MM/DD/YYYY': '%m/%d/%Y'}
CANONICAL_COLUMNS = {'date', 'reference', 'money_in', 'money_out', 'description', 'balance'}


def mapping_profile(s, data):
    mapping_id = data.get('mappingId')
    if mapping_id:
        profile = next((row for row in s['settings'].get('bankImportMappings', []) if row.get('id') == mapping_id), None)
        require(profile is not None and profile.get('active', True), 'Choose an active bank import mapping.')
        return {**DEFAULT_MAPPING, **profile.get('columns', {}), 'delimiter': profile.get('delimiter', ','),
                'dateFormat': profile.get('dateFormat', 'YYYY-MM-DD'),
                'decimalSeparator': profile.get('decimalSeparator', '.'),
                'thousandsSeparator': profile.get('thousandsSeparator', '')}
    supplied = data.get('mapping') or {}
    require(isinstance(supplied, dict), 'Bank import mapping must be an object.')
    return {**DEFAULT_MAPPING, **supplied}


def validate_mapping(mapping):
    require(set(mapping).issubset(CANONICAL_COLUMNS | {'delimiter', 'dateFormat', 'decimalSeparator', 'thousandsSeparator'}), 'Unknown mapping field.')
    require(mapping.get('decimalSeparator', '.') in ('.', ','), 'Choose dot or comma decimals.')
    require(mapping.get('thousandsSeparator', '') in ('', ',', '.', ' '), 'Unsupported thousands separator.')
    require(mapping.get('decimalSeparator', '.') != mapping.get('thousandsSeparator', ''),
            'Decimal and thousands separators must differ.')
    require(isinstance(mapping.get('dateFormat', 'YYYY-MM-DD'), str)
            and mapping.get('dateFormat', 'YYYY-MM-DD') in DATE_FORMATS, 'Choose a supported date format.')
    require(all(isinstance(mapping.get(key, ''), str) for key in CANONICAL_COLUMNS),
            'Source headers must be text.')
    require(mapping.get('delimiter') in (',', ';', '\t', '|'),
            'Choose comma, semicolon, tab or pipe as the delimiter.')
    require(all(isinstance(mapping.get(key), str) and 0 < len(mapping[key]) <= 100
                for key in ('date', 'reference', 'money_in', 'money_out')),
            'Date, reference, money-in and money-out source columns are required.')
    sources = [mapping[key] for key in CANONICAL_COLUMNS if mapping.get(key)]
    require(len(sources) == len(set(sources)), 'Each source column can be mapped only once.')
    return mapping


def fingerprint(data):
    values = {k: data.get(k) for k in ("csv", "bankLedger", "statementCurrency", "mappingId")}
    values['mapping'] = data.get('mapping') or None
    values['delimiter'] = (data.get('mapping') or {}).get('delimiter', data.get('delimiter', ','))
    opening = data.get('openingBalance')
    values['openingBalance'] = None if opening in (None, '') else str(decimal_value(opening, 'Opening balance').normalize())
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def decimal_value(value, label):
    result = dec(value)
    require(abs(result) <= dec('999999999999.99'), label + ' exceeds the supported amount.')
    require(result == result.quantize(dec('.01')), label + ' must have at most two decimal places.')
    return result


def localized_amount(value, label, mapping):
    decimal = mapping.get('decimalSeparator', '.')
    grouping = mapping.get('thousandsSeparator', '')
    integer = r'[0-9]+'
    if grouping:
        integer = rf'(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(grouping)}[0-9]{{3}})+)'
    value = value.strip()
    require(bool(re.fullmatch(rf'[+-]?{integer}(?:{re.escape(decimal)}[0-9]{{1,2}})?', value)),
            label + ' does not match the selected number format.')
    if grouping:
        value = value.replace(grouping, '')
    return decimal_value(value.replace(decimal, '.'), label)


def parse(data, mapping=None):
    raw = data.get('csv')
    require(isinstance(raw, str) and 0 < len(raw.encode()) <= 1_000_000, 'Upload a CSV no larger than 1 MB.')
    mapping = validate_mapping(mapping or DEFAULT_MAPPING)
    reader = csv.DictReader(io.StringIO(raw.lstrip('\ufeff')), delimiter=mapping['delimiter'], strict=True)
    required = {mapping[key] for key in ('date', 'reference', 'money_in', 'money_out')}
    try:
        headers = reader.fieldnames or []
    except csv.Error:
        raise RuleError('Malformed CSV quoting or field size.') from None
    require(len(headers) == len(set(headers)) and required.issubset(headers),
            'CSV is missing one or more required mapped columns.')
    opening = data.get('openingBalance')
    running = None if opening in (None, '') else decimal_value(opening, 'Opening balance')
    balance_column = mapping.get('balance')
    require(not balance_column or balance_column not in headers or running is not None,
            'Opening balance is required when a mapped balance column is supplied.')
    rows, refs = [], set()
    incoming = outgoing = dec(0)
    previous_date = None
    try:
        for number, row in enumerate(reader, 2):
            require(len(rows) < 500, 'Import up to 500 statement rows at a time.')
            require(None not in row and all(v is not None for v in row.values()), f'Row {number}: incorrect column count.')
            reference = row[mapping['reference']].strip()
            require(reference and len(reference) <= 200, f'Row {number}: reference is required and must fit 200 characters.')
            require(reference.casefold() not in refs, f'Row {number}: duplicate reference in file.')
            refs.add(reference.casefold())
            day = row[mapping['date']].strip()
            try:
                pattern = DATE_FORMATS[mapping.get('dateFormat', 'YYYY-MM-DD')]
                parsed_date = datetime.strptime(day, pattern).date()
                require(parsed_date.strftime(pattern) == day, 'Date must exactly match the selected format.')
            except ValueError:
                raise RuleError(f'Row {number}: date must match {mapping.get("dateFormat", "YYYY-MM-DD")}.') from None
            day = parsed_date.isoformat()
            require(previous_date is None or parsed_date >= previous_date, f'Row {number}: statement must be sorted oldest to newest.')
            previous_date = parsed_date
            money_in = localized_amount(row[mapping['money_in']].strip() or '0', f'Row {number} money in', mapping)
            money_out = localized_amount(row[mapping['money_out']].strip() or '0', f'Row {number} money out', mapping)
            require(money_in >= 0 and money_out >= 0 and ((money_in > 0) != (money_out > 0)),
                    f'Row {number}: exactly one of money_in and money_out must be positive.')
            if running is not None:
                running += money_in - money_out
                if balance_column in row:
                    require(localized_amount(row[balance_column], f'Row {number} balance', mapping) == running,
                            f'Row {number}: running balance does not reconcile.')
            incoming += money_in
            outgoing += money_out
            rows.append(dict(date=day, reference=reference, amount=amount(money_in or money_out, True),
                             direction='debit' if money_in else 'credit',
                             description=row.get(mapping.get('description', ''), '').strip()))
    except csv.Error:
        raise RuleError('Malformed CSV quoting or field size.') from None
    require(rows, 'The CSV contains no statement transactions.')
    return rows, dict(rowCount=len(rows), moneyIn=str(incoming), moneyOut=str(outgoing),
                      closingBalance=str(running) if running is not None else None)


def import_statement(s, data, actor, preview=False):
    require(actor['role'] in {'admin', 'finance'}, 'Finance access is required.')
    mapping = validate_mapping(mapping_profile(s, data))
    preview_hash = fingerprint({**data, 'mapping': mapping, 'mappingId': data.get('mappingId') or None})
    require(preview or data.get('previewHash') == preview_hash, 'Preview the current file and settings before importing.')
    ledger = active_ledger(s, data.get('bankLedger', 'LED-BANK'))
    currency = ledger.get('currency') or s['settings']['currency']
    require(data.get('statementCurrency') == currency, 'Statement currency must match the selected bank ledger.')
    rows, summary = parse(data, mapping)
    working = deepcopy(s)
    batch = identifier(working, 'BIMPORT')
    records = []
    for row in rows:
        r = finance_action(working, 'bankStatement', dict(row, bankLedger=ledger['id']), actor)
        r.update(importBatch=batch, importedBy=actor['id'], currency=currency)
        records.append(r)
    summary.update(id=batch, currency=currency, previewHash=preview_hash, rows=records)
    if not preview:
        s.clear()
        s.update(working)
    return summary


def save_mapping(s, data, actor):
    require(actor['role'] in {'admin', 'finance'}, 'Finance access is required.')
    name = data.get('name', '')
    require(isinstance(name, str) and 1 <= len(name.strip()) <= 100, 'Mapping name is required.')
    name = name.strip()
    require(isinstance(data.get('columns', {}), dict), 'Columns must be an object.')
    require(isinstance(data.get('active', True), bool), 'Active must be true or false.')
    mapping = validate_mapping({**DEFAULT_MAPPING, **(data.get('columns') or {}),
                                'delimiter': data.get('delimiter', ','), 'dateFormat': data.get('dateFormat', 'YYYY-MM-DD'),
                                'decimalSeparator': data.get('decimalSeparator', '.'),
                                'thousandsSeparator': data.get('thousandsSeparator', '')})
    profiles = s['settings'].setdefault('bankImportMappings', [])
    existing = next((row for row in profiles if row.get('id') == data.get('id')), None)
    require(not data.get('id') or existing is not None, 'Mapping profile not found.')
    if existing:
        existing.update(decimalSeparator=mapping['decimalSeparator'], thousandsSeparator=mapping['thousandsSeparator'])
        existing.update(name=name, columns={key: mapping[key] for key in CANONICAL_COLUMNS},
                        delimiter=mapping['delimiter'], dateFormat=mapping['dateFormat'], active=bool(data.get('active', True)))
        return existing
    profile = dict(id=identifier(s, 'BMAP'), name=name,
                   columns={key: mapping[key] for key in CANONICAL_COLUMNS},
                   delimiter=mapping['delimiter'], dateFormat=mapping['dateFormat'], active=True)
    profiles.append(profile)
    profile.update(decimalSeparator=mapping['decimalSeparator'], thousandsSeparator=mapping['thousandsSeparator'])
    return profile


def suggestions(s, statement_id):
    statement = get(s, 'bankStatements', statement_id)
    require(statement['status'] == 'Unreconciled', 'Choose an unreconciled statement line.')
    candidates = []
    for collection in ('payments', 'customerPayments', 'partyFunds', 'fundRefunds'):
        for row in s[collection]:
            if row.get('reconciledStatement') or row.get('status') == 'Reversed':
                continue
            if (row.get('bankLedger') != statement['bankLedger'] or dec(row['amount']) <= 0
                    or dec(row['amount']) > dec(statement['amount'])):
                continue
            if collection == 'partyFunds':
                direction = 'credit' if row['side'] == 'supplier' else 'debit'
            elif collection == 'fundRefunds':
                direction = 'debit' if row['side'] == 'supplier' else 'credit'
            else:
                direction = 'credit' if collection == 'payments' else 'debit'
            if direction != statement['direction'] or not row.get('date'):
                continue
            difference = abs((date.fromisoformat(row['date']) - date.fromisoformat(statement['date'])).days)
            if difference > 7:
                continue
            same_reference = row.get('reference', '').strip().casefold() == statement['reference'].strip().casefold()
            candidates.append(dict(collection=collection, transaction=row['id'], date=row['date'], amount=row['amount'],
                reference=row.get('reference', ''), daysApart=difference, exactReference=same_reference))
    candidates.sort(key=lambda c: (not c['exactReference'], c['daysApart'], c['collection'], c['transaction']))
    exact = [c for c in candidates if dec(c['amount']) == dec(statement['amount'])]
    groups = []
    # Suggest only bounded pairs/triples. Staff can select up to 100 candidates manually.
    bounded = candidates[:30]
    for first in range(len(bounded)):
        for second in range(first + 1, len(bounded)):
            pair = [bounded[first], bounded[second]]
            total = sum((dec(c['amount']) for c in pair), dec(0))
            if total == dec(statement['amount']):
                groups.append(pair)
            elif total < dec(statement['amount']):
                for third in range(second + 1, len(bounded)):
                    group = pair + [bounded[third]]
                    if sum((dec(c['amount']) for c in group), dec(0)) == dec(statement['amount']):
                        groups.append(group)
            if len(groups) >= 20:
                break
        if len(groups) >= 20:
            break
    return dict(statement=statement_id, statementAmount=statement['amount'], candidates=candidates,
                exactCandidates=exact, groupCandidates=groups, ambiguous=len(exact) + len(groups) > 1,
                automaticMatch=False)
