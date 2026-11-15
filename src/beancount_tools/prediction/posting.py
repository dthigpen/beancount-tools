import re
from collections import defaultdict, Counter
from beancount.core.data import Transaction, Posting


class SimplePostingPRedictor:
    def __init__(self, debug=False):
        # (normalized narration, existing_account) -> Counter(missing_account)
        self.model = defaultdict(Counter)
        self.debug = debug

    # -----------------
    # Debug helper
    # -----------------
    def log(self, *args):
        if self.debug:
            print('[Predictor]', *args)

    # -----------------
    # Normalization
    # -----------------
    def normalize(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r'\d+', '', text)
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    # -----------------
    # Training
    # -----------------
    def train(self, transactions):
        self.model.clear()

        for txn in transactions:
            narration = self.normalize(txn.narration or '')

            accounts = [p.account for p in txn.postings]

            # only learn from simple 2-posting transactions
            if len(accounts) != 2:
                continue

            acc1, acc2 = accounts

            # learn both directions
            self.model[(narration, acc1)][acc2] += 1
            self.model[(narration, acc2)][acc1] += 1

        self.log(f'Training complete. Model size: {len(self.model)}')

    # -----------------
    # Similarity
    # -----------------
    def similarity(self, a: str, b: str) -> float:
        set_a = set(a.split())
        set_b = set(b.split())

        if not set_a or not set_b:
            return 0.0

        return len(set_a & set_b) / len(set_a | set_b)

    # -----------------
    # Prediction
    # -----------------
    def predict_account(self, narration: str, existing_account: str):
        narration = self.normalize(narration)

        best_score = 0
        best_account = None

        for (known_narration, known_account), counter in self.model.items():
            # must match the existing account exactly
            if known_account != existing_account:
                continue

            score = self.similarity(narration, known_narration)

            if score > best_score:
                best_score = score
                best_account = counter.most_common(1)[0][0]

        self.log(
            f"Predict: '{narration}' + {existing_account} → {best_account} (score={best_score})"
        )

        return best_account, best_score

    # -----------------
    # Apply prediction
    # -----------------
    def apply_prediction(self, txn: Transaction):
        if not txn.postings:
            return txn

        # assume importer provides exactly one account
        existing_accounts = [p.account for p in txn.postings]

        # only handle simple case: one known account
        if len(existing_accounts) != 1:
            self.log('Skipping txn (not single posting):', txn.narration)
            return txn

        existing_account = existing_accounts[0]

        account, score = self.predict_account(txn.narration or '', existing_account)

        # threshold (tune if needed)
        if not account or score < 0.4:
            self.log('No confident prediction.')
            return txn

        # don't duplicate
        if account in existing_accounts:
            self.log('Prediction matches existing account, skipping.')
            return txn

        new_posting = Posting(
            account=account,
            units=None,
            cost=None,
            price=None,
            flag=None,
            meta=None,
        )

        txn.postings.append(new_posting)

        self.log(f'Applied: {existing_account} + {account} (score={score})')

        return txn

    # -----------------
    # Hook
    # -----------------
    def hook(self, imported_entries, existing_entries):
        transactions = [e for e in existing_entries if isinstance(e, Transaction)]

        self.train(transactions)

        result = []

        for filename, entries, account, importer in imported_entries:
            new_entries = []

            for entry in entries:
                if isinstance(entry, Transaction):
                    entry = self.apply_prediction(entry)

                new_entries.append(entry)

            result.append((filename, new_entries, account, importer))

        return result
