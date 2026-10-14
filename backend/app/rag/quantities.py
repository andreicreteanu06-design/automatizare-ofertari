"""Strict scalar quantities. Preserve source text; normalize only known units."""
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import re
import unicodedata

import pint

UNITS = {'kg': 'kg', 'g': 'g', 'mg': 'mg', 'mm': 'mm', 'cm': 'cm', 'm': 'm',
         'Pa': 'Pa', 'kPa': 'kPa', 'MPa': 'MPa', 'bar': 'bar',
         '°C': 'degC', '°c': 'degC', 'K': 'kelvin', 'N': 'newton',
         'N·m': 'newton * meter', 'Nm': 'newton * meter', 'N m': 'newton * meter'}
TARGETS = {'masa': 'kg', 'lungime': 'mm', 'latime': 'mm', 'inaltime': 'mm', 'diametru': 'mm',
           'presiune': 'Pa', 'temperatura': 'kelvin', 'forta': 'newton', 'cuplu': 'newton * meter'}
SCALAR = re.compile(r'^\s*([-+]?\d+(?:[.,]\d+)?)\s*([^\d]+?)\s*$')


@lru_cache(maxsize=1)
def registry():
    return pint.UnitRegistry(non_int_type=Decimal)


def parse_quantity(value, prop):
    match = SCALAR.fullmatch(value)
    if not match or prop not in TARGETS:
        return None
    unit = UNITS.get(match[2])
    if not unit:
        return None
    try:
        quantity = registry().Quantity(Decimal(match[1].replace(',', '.')), unit).to(TARGETS[prop])
        return {'value': format(quantity.magnitude.normalize(), 'f'), 'unit': TARGETS[prop],
                'original_value': value, 'original_unit': match[2]}
    except (pint.DimensionalityError, pint.OffsetUnitCalculusError, InvalidOperation):
        return None


def comparison_key(value, prop):
    parsed = parse_quantity(value, prop)
    return (parsed['value'], parsed['unit']) if parsed else ('literal', value)


def scalar_from_prose(text, aliases):
    # Preserve SI symbol case (MPa is not mPa) while ignoring Romanian accents.
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    unit_pattern = '|'.join(re.escape(u) for u in sorted([*UNITS, 'EUR', 'RON', 'USD'], key=len, reverse=True))
    match = re.search(r'\b(?:' + '|'.join(aliases) + r')\b\s*(?:(?:este|de|are|is|of)\s*)*[:=]?\s*([-+]?\d+(?:[.,]\d+)?\s*(?:' + unit_pattern + r'))(?!\w)', text, re.I)
    return match[1] if match else None
