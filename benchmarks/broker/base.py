"""Reuse the baseline contracts without importing its separate Spec root.

The loader names objects only below an entry's directory. These baseline
modules live outside it, so the benchmark performs their naming pass explicitly
before composing them. No membership is inferred from this pass.
"""

from examples.broker import accounts, payments, profile

from analint.loader.python_loader import collect_from_modules

collect_from_modules([accounts, payments, profile])
trading_accounts = accounts.trading_accounts
cash_payments = payments.payments
client_profile = profile.profile
