"""
Bond / Fixed Income service.
Loads NTB auction data from the JSON files extracted from the CBN Primary Market Excel.
Provides current offerings, historical rate charts, and purchase calculation logic.
"""
import json
import os
from datetime import datetime, date
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


def _load_json(filename: str) -> list:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, 'r') as f:
        return json.load(f)


def get_history() -> list:
    return _load_json('ntb_history.json')


def get_chart_data() -> list:
    """Annual average rates per tenor — used for the historical rate chart."""
    return _load_json('ntb_chart.json')


def get_current_offerings() -> list[dict]:
    """Return the single most recent auction entry for each tenor (91, 182, 364)."""
    history = get_history()
    seen = {}
    for row in history:  # already sorted newest-first
        t = row['tenor']
        if t not in seen and row.get('stopRate'):
            seen[t] = row
        if len(seen) == 3:
            break

    offerings = []
    for tenor in (91, 182, 364):
        r = seen.get(tenor)
        if not r:
            continue

        rate = r['stopRate']
        # Build instrument ID
        instrument_id = f"NTB-{tenor}-{r['auctionDate']}"

        # Tenor label
        if tenor == 91:
            label = '91-Day T-Bill'
            risk = 'Very Low'
            desc = 'Short-term government security. Best for liquid savings with guaranteed return above bank rates.'
        elif tenor == 182:
            label = '182-Day T-Bill'
            risk = 'Very Low'
            desc = 'Medium short-term government security. Ideal for 6-month cash management with competitive yield.'
        else:
            label = '364-Day T-Bill'
            risk = 'Very Low'
            desc = 'One-year government security. Highest yield among T-Bills. Suitable as a fixed-income core holding.'

        # Next auction (every 2 weeks; approximate)
        offerings.append({
            'instrument_id': instrument_id,
            'security_type': 'NTB',
            'tenor': tenor,
            'label': label,
            'description': desc,
            'risk': risk,
            'auction_date': r['auctionDate'],
            'maturity_date': r['maturityDate'],
            'stop_rate': rate,          # annualised %
            'min_investment': 50_000,   # ₦50,000 minimum (retail)
            'denominations': [50_000, 100_000, 500_000, 1_000_000, 5_000_000],
            'amt_offered_mn': r.get('amtOffered', 0),
            'total_subscription_mn': r.get('totalSubscription', 0),
            'oversubscription_ratio': round(
                r['totalSubscription'] / r['amtOffered'], 2
            ) if r.get('amtOffered') and r['amtOffered'] > 0 else None,
            'settlement': 'T+2',
            'interest_payment': 'Upfront (discount)',
            'issuer': 'Federal Government of Nigeria',
            'guarantor': 'Central Bank of Nigeria (CBN)',
            'coupon_type': 'Discount (zero-coupon)',
        })
    return offerings


def calculate_ntb_purchase(face_value: float, tenor: int, stop_rate: float) -> dict:
    """
    NTBs are discount instruments:
      discount_amount = face_value × (stop_rate/100) × (tenor/365)
      purchase_price  = face_value − discount_amount
      At maturity, investor receives face_value.
    """
    discount = face_value * (stop_rate / 100) * (tenor / 365)
    purchase_price = face_value - discount
    effective_yield = (discount / purchase_price) * (365 / tenor) * 100

    return {
        'face_value': round(face_value, 2),
        'discount_amount': round(discount, 2),
        'purchase_price': round(purchase_price, 2),
        'expected_return': round(face_value, 2),
        'interest_earned': round(discount, 2),
        'effective_yield': round(effective_yield, 4),
        'annualised_rate': stop_rate,
    }


def get_historical_rate_trend(tenor: int, from_year: int = 2015) -> list[dict]:
    """Return quarterly average stop rates for a given tenor from from_year."""
    history = get_history()
    from collections import defaultdict
    quarterly: dict = defaultdict(list)
    for r in history:
        if r['tenor'] != tenor or not r.get('stopRate'):
            continue
        yr = int(r['auctionDate'][:4])
        if yr < from_year:
            continue
        mo = int(r['auctionDate'][5:7])
        q = (mo - 1) // 3 + 1
        key = f'{yr}-Q{q}'
        quarterly[key].append(r['stopRate'])

    result = []
    for key in sorted(quarterly.keys()):
        rates = quarterly[key]
        result.append({
            'period': key,
            'avg_rate': round(sum(rates) / len(rates), 2),
            'min_rate': min(rates),
            'max_rate': max(rates),
            'auctions': len(rates),
        })
    return result
