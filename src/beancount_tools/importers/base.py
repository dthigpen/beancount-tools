from beangulp import mimetypes
from beangulp.importers import csvbase
from beancount.core import data

import datetime
from pathlib import Path
import hashlib

from beangulp import extract, similar


class BaseImporter(csvbase.Importer):
    def __init__(
        self,
        *args,
        csv_header=None,
        file_name_identifier=None,
        flip_sign=False,
        add_import_id=False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.csv_header = csv_header
        self.file_name_identifier = file_name_identifier
        self.flip_sign = flip_sign
        self.add_import_id = add_import_id

    def identify(self, filepath):
        mimetype, encoding = mimetypes.guess_type(filepath)
        if mimetype != 'text/csv':
            return False
        if (
            self.file_name_identifier
            and self.file_name_identifier.lower() not in Path(filepath).name.lower()
        ):
            return False
        with open(filepath) as fd:
            head = fd.read(1024)
        return head.startswith(self.csv_header)

    def make_import_id(self, filename, lineno, row):
        key = f'{filename}|{row.date}|{row.amount}|{row.narration}|{lineno}'
        length = 12
        return hashlib.sha1(key.encode()).hexdigest()[:length]

    def metadata(self, filepath, lineno, row):
        if self.add_import_id:
            import_id = self.make_import_id(filepath, lineno, row)
            return data.new_metadata(filepath, lineno, kvlist={'import_id': import_id})
        else:
            return super().metadata(filepath=filepath, lineno=lineno, row=row)

    def filename(self, filepath):
        account_str = self.file_name_identifier
        if not account_str:
            account_str = '-'.join(self.account(filepath).split(':')[1:])
        if not account_str:
            account_str = ''
        return f'{account_str}.csv'

    def finalize(self, txn, row):
        if self.flip_sign:
            if isinstance(txn, data.Transaction):
                new_postings = []
                for posting in txn.postings:
                    flipped = -posting.units
                    new_postings.append(posting._replace(units=flipped))
                txn = txn._replace(postings=new_postings)
            elif isinstance(txn, data.Balance):
                txn = txn._replace(amount=-txn.amount)

        return txn

    @staticmethod
    def cmp(entry1: data.Directive, entry2: data.Directive):
        are_txns = isinstance(entry1, data.Transaction) and isinstance(
            entry2, data.Transaction
        )
        default_cmp_result = similar.heuristic_comparator()(entry1, entry2)
        if are_txns:
            return entry1.narration == entry2.narration and default_cmp_result
        return default_cmp_result

    def deduplicate(self, entries, existing):
        """
        This is overriden to use a window of 0 days delta and compare narrations.
        Previously *different* txns were flagged as duplicate even though
        they have different narrations.
        The self.cmp was modified to check that narrations are actually equal.
        Example:
        2025-12-30 "Auto Transfer Checking to Savings 1234" 50.00
        2025-01-01 "Auto Transfer Checking to Savings 9999" 50.00
        """
        # return super().deduplicate(entries, existing)
        window = datetime.timedelta(days=0)
        extract.mark_duplicate_entries(entries, existing, window, self.cmp)
