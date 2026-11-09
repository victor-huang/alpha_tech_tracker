from alpha_tech_tracker.research.recommended_rules import RECOMMENDED, SMALL_BASE, SMALL_VARIANTS
from alpha_tech_tracker.research.selection_filters import VARIANTS


class TestRecommended:
    def test_large_ranks_on_180_day_return_with_breakout_slots(self):
        name, variant, _ = RECOMMENDED["Large"]

        assert (name, bool(variant.boost_groups)) == ("ret180/vol^0.5+slots", True)

    def test_small_is_the_dilution_and_gross_profit_rule_without_safeguards(self):
        _, variant, _ = RECOMMENDED["Small"]

        assert variant is VARIANTS[SMALL_BASE]


class TestSmallVariants:
    def test_safeguard_variants_only_change_liquidity_and_streak(self):
        both = SMALL_VARIANTS[f"{SMALL_BASE}+liquid+streak_cap"]

        assert both._replace(liquid=False, max_streak=None) == VARIANTS[SMALL_BASE]
