"""Unit tests. Run with:  python -m unittest discover -s tests -v"""

from __future__ import annotations

import base64
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agent import indicators, strategy
from agent.backtest import run_backtest
from agent.brokers.base import Account, Bar, BrokerError, Position
from agent.brokers.kraken import KrakenBroker
from agent.brokers.sim import SimBroker, synthetic_bars
from agent.config import LIVE_CONFIRM_PHRASE, Config, ConfigError, Limits
from agent.engine import CycleReport, Engine
from agent.ledger import Ledger
from agent.protection import StopBook, StopState
from agent.risk import RiskEngine


def make_bars(closes: list[float], symbol: str = "TEST") -> list[Bar]:
    start = date(2024, 1, 1)
    return [
        Bar(symbol, start + timedelta(days=i), close, close * 1.01, close * 0.99, close, 1_000)
        for i, close in enumerate(closes)
    ]


def temp_cfg(tmpdir: str, **overrides) -> Config:
    limits = Limits(**overrides.pop("limits", {}))
    defaults = dict(
        broker="sim",
        alpaca_env="paper",
        strategy="trend",
        universe=["SPY"],
        limits=limits,
        halt_file=os.path.join(tmpdir, "HALT"),
        db_path=os.path.join(tmpdir, "test.db"),
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestIndicators(unittest.TestCase):
    def test_sma_needs_full_window(self):
        self.assertIsNone(indicators.sma([1, 2], 3))
        self.assertEqual(indicators.sma([1, 2, 3], 3), 2.0)

    def test_sma_uses_only_the_last_window(self):
        self.assertEqual(indicators.sma([100, 1, 2, 3], 3), 2.0)

    def test_rsi_bounds(self):
        rising = indicators.rsi(list(range(1, 40)), 14)
        falling = indicators.rsi(list(range(40, 1, -1)), 14)
        self.assertGreater(rising, 95)
        self.assertLess(falling, 5)

    def test_rsi_insufficient_history(self):
        self.assertIsNone(indicators.rsi([1, 2, 3], 14))

    def test_atr_is_positive(self):
        bars = make_bars([10, 11, 12, 11, 13, 12, 14, 15, 14, 16, 17, 16, 18, 19, 20])
        value = indicators.atr(bars, 14)
        self.assertIsNotNone(value)
        self.assertGreater(value, 0)


class TestStrategy(unittest.TestCase):
    def test_warmup_blocks_signals(self):
        trend = strategy.TrendStrategy()
        signal = trend.evaluate(make_bars([100.0] * 10), held=False)
        self.assertEqual(signal.action, strategy.HOLD)
        self.assertIn("warming up", signal.reason)

    def test_uptrend_produces_entry_with_stop_below_price(self):
        trend = strategy.TrendStrategy()
        closes = [100 + i * 0.5 for i in range(260)]
        signal = trend.evaluate(make_bars(closes), held=False)
        self.assertEqual(signal.action, strategy.ENTER)
        self.assertLess(signal.stop_price, signal.price)
        self.assertGreater(signal.score, 0)

    def test_downtrend_gives_no_entry_and_exits_a_holding(self):
        trend = strategy.TrendStrategy()
        bars = make_bars([300 - i * 0.5 for i in range(260)])
        self.assertEqual(trend.evaluate(bars, held=False).action, strategy.HOLD)
        self.assertEqual(trend.evaluate(bars, held=True).action, strategy.EXIT)

    def test_meanrev_only_buys_dips_inside_an_uptrend(self):
        meanrev = strategy.MeanReversionStrategy()
        # Long uptrend, then a sharp multi-day dip that stays above the MA200.
        closes = [100 + i * 0.5 for i in range(250)] + [220, 210, 200]
        signal = meanrev.evaluate(make_bars(closes), held=False)
        self.assertEqual(signal.action, strategy.ENTER)

        downtrend = make_bars([300 - i for i in range(260)])
        self.assertEqual(meanrev.evaluate(downtrend, held=False).action, strategy.HOLD)

    def test_stop_is_clamped_when_volatility_exceeds_price(self):
        """The crypto case: k*ATR can exceed the price itself."""
        trend = strategy.TrendStrategy()
        # Violently volatile but still trending up.
        closes = [100 + i * 3 + (60 if i % 2 else -60) for i in range(260)]
        signal = trend.evaluate(make_bars(closes), held=False)
        self.assertGreater(signal.stop_price, 0, "a stop must never be negative")
        self.assertLess(signal.stop_price, signal.price, "a stop must sit below price")

    def test_clamp_floors_the_stop_at_max_stop_fraction(self):
        trend = strategy.TrendStrategy()
        trend.max_stop_fraction = 0.20
        self.assertAlmostEqual(trend._clamp_stop(100.0, -50.0), 80.0, places=6)
        self.assertAlmostEqual(trend._clamp_stop(100.0, 0.0), 80.0, places=6)
        self.assertAlmostEqual(trend._clamp_stop(100.0, 150.0), 80.0, places=6)
        # A tighter-than-ceiling stop is kept as-is.
        self.assertAlmostEqual(trend._clamp_stop(100.0, 95.0), 95.0, places=6)
        # A looser one is pulled up to the ceiling.
        self.assertAlmostEqual(trend._clamp_stop(100.0, 50.0), 80.0, places=6)

    def test_build_applies_the_configured_stop_ceiling(self):
        built = strategy.build("trend", 0.05)
        self.assertAlmostEqual(built.max_stop_fraction, 0.05)

    def test_build_rejects_an_impossible_stop_ceiling(self):
        for bad in (0.0, 1.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                strategy.build("trend", bad)

    def test_build_rejects_unknown_strategy(self):
        with self.assertRaises(ValueError):
            strategy.build("moon-phase")


class TestConfig(unittest.TestCase):
    def test_live_requires_exact_confirm_phrase(self):
        armed = Config(alpaca_env="live", live_confirm=LIVE_CONFIRM_PHRASE)
        self.assertTrue(armed.is_live)
        self.assertFalse(armed.live_requested_but_unarmed)

        for bad in ("", "yes", LIVE_CONFIRM_PHRASE.lower(), LIVE_CONFIRM_PHRASE + "!"):
            cfg = Config(alpaca_env="live", live_confirm=bad)
            self.assertFalse(cfg.is_live, bad)
            self.assertTrue(cfg.live_requested_but_unarmed, bad)

    def test_paper_is_never_live(self):
        self.assertFalse(Config(alpaca_env="paper", live_confirm=LIVE_CONFIRM_PHRASE).is_live)

    def test_endpoint_matches_mode(self):
        self.assertIn("paper-api", Config(alpaca_env="paper").trading_base_url)
        self.assertNotIn("paper", Config(alpaca_env="live").trading_base_url)

    def test_limit_validation(self):
        Limits().validate()
        with self.assertRaises(ConfigError):
            Limits(min_order_notional=0.5).validate()
        with self.assertRaises(ConfigError):
            Limits(max_order_notional=1.0, min_order_notional=2.0).validate()
        with self.assertRaises(ConfigError):
            Limits(max_deployed=5.0, max_order_notional=15.0).validate()
        with self.assertRaises(ConfigError):
            Limits(daily_loss_limit_pct=0).validate()
        with self.assertRaises(ConfigError):
            Limits(risk_per_trade_pct=101).validate()


class RiskTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.cfg = temp_cfg(self.tmpdir)
        self.ledger = Ledger(self.cfg.db_path)
        self.risk = RiskEngine(self.cfg, self.ledger)
        self.account = Account("A1", "USD", cash=50.0, equity=50.0, buying_power=50.0)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()


class TestRiskSizing(RiskTestBase):
    def test_risk_based_size_respects_stop_distance(self):
        # 1.5% of 50 = 0.75 risked; a 10% stop distance implies a 7.50 position.
        sizing = self.risk.size_entry(
            symbol="SPY", price=100.0, stop_price=90.0, account=self.account, positions=[]
        )
        self.assertTrue(sizing.approved)
        self.assertAlmostEqual(sizing.notional, 7.50, places=2)

    def test_size_never_exceeds_the_hard_cap(self):
        # A very tight stop implies a huge position; the cap must bind.
        sizing = self.risk.size_entry(
            symbol="SPY", price=100.0, stop_price=99.9, account=self.account, positions=[]
        )
        self.assertLessEqual(sizing.notional, self.cfg.limits.max_order_notional)

    def test_missing_stop_falls_back_to_the_cap_not_beyond(self):
        sizing = self.risk.size_entry(
            symbol="SPY", price=100.0, stop_price=None, account=self.account, positions=[]
        )
        self.assertLessEqual(sizing.notional, self.cfg.limits.max_order_notional)

    def test_refuses_to_double_up_on_a_held_symbol(self):
        held = [Position("SPY", 0.1, 100.0, 10.0, 0.0)]
        sizing = self.risk.size_entry(
            symbol="SPY", price=100.0, stop_price=90.0, account=self.account, positions=held
        )
        self.assertFalse(sizing.approved)
        self.assertEqual(sizing.veto.code, "already_held")

    def test_max_positions_cap(self):
        held = [
            Position("AAA", 0.1, 100.0, 10.0, 0.0),
            Position("BBB", 0.1, 100.0, 10.0, 0.0),
        ]
        sizing = self.risk.size_entry(
            symbol="SPY", price=100.0, stop_price=90.0, account=self.account, positions=held
        )
        self.assertEqual(sizing.veto.code, "max_positions")

    def test_deployment_cap_blocks_when_capital_is_committed(self):
        cfg = temp_cfg(self.tmpdir, limits={"max_deployed": 50.0, "max_positions": 5})
        risk = RiskEngine(cfg, self.ledger)
        held = [Position("AAA", 1.0, 49.0, 49.0, 0.0)]
        sizing = risk.size_entry(
            symbol="SPY", price=100.0, stop_price=90.0, account=self.account, positions=held
        )
        self.assertEqual(sizing.veto.code, "deploy_cap")

    def test_low_cash_produces_too_small_veto_not_a_bad_order(self):
        broke = Account("A1", "USD", cash=0.40, equity=50.0, buying_power=0.40)
        sizing = self.risk.size_entry(
            symbol="SPY", price=100.0, stop_price=90.0, account=broke, positions=[]
        )
        self.assertFalse(sizing.approved)
        self.assertEqual(sizing.veto.code, "too_small")

    def test_rejects_non_positive_price(self):
        sizing = self.risk.size_entry(
            symbol="SPY", price=0.0, stop_price=None, account=self.account, positions=[]
        )
        self.assertEqual(sizing.veto.code, "bad_price")


class TestRiskPreflight(RiskTestBase):
    def codes(self, account=None):
        return {v.code for v in self.risk.preflight(account or self.account)}

    def test_clean_account_passes(self):
        self.assertEqual(self.codes(), set())

    def test_halt_file_stops_everything_permanently(self):
        Path(self.cfg.halt_file).write_text("stop")
        vetoes = self.risk.preflight(self.account)
        self.assertIn("halt_file", {v.code for v in vetoes})
        self.assertTrue(next(v for v in vetoes if v.code == "halt_file").permanent)

    def test_live_without_confirmation_is_vetoed(self):
        cfg = temp_cfg(self.tmpdir, broker="alpaca", alpaca_env="live", live_confirm="sure")
        risk = RiskEngine(cfg, self.ledger)
        self.assertIn("live_unarmed", {v.code for v in risk.preflight(self.account)})

    def test_blocked_account_is_vetoed(self):
        blocked = Account("A1", "USD", 50, 50, 50, trading_blocked=True)
        self.assertIn("account_blocked", self.codes(blocked))

    def test_daily_loss_limit_trips(self):
        self.ledger.record_equity(50.0, 50.0)  # today's opening equity
        down = Account("A1", "USD", cash=47.0, equity=47.0, buying_power=47.0)  # -6%
        self.assertIn("daily_loss", self.codes(down))

    def test_daily_loss_limit_not_tripped_by_small_move(self):
        self.ledger.record_equity(50.0, 50.0)
        down = Account("A1", "USD", cash=49.0, equity=49.0, buying_power=49.0)  # -2%
        self.assertNotIn("daily_loss", self.codes(down))

    def test_max_drawdown_is_permanent(self):
        self.ledger.set_state("high_water_mark", 100.0)
        down = Account("A1", "USD", cash=70.0, equity=70.0, buying_power=70.0)  # -30%
        vetoes = self.risk.preflight(down)
        drawdown = next(v for v in vetoes if v.code == "max_drawdown")
        self.assertTrue(drawdown.permanent)

    def test_daily_order_cap(self):
        run_id = self.ledger.start_run(
            mode="test", broker="sim", strategy="trend", equity=50, cash=50
        )
        for i in range(self.cfg.limits.max_orders_per_day):
            self.ledger.record_order(
                run_id,
                broker_order_id=f"o{i}",
                symbol="SPY",
                side="buy",
                notional=5.0,
                qty=None,
                status="filled",
                fill_price=100.0,
            )
        self.assertIn("order_cap", self.codes())

    def test_day_trade_guard_blocks_same_day_round_trip(self):
        run_id = self.ledger.start_run(
            mode="test", broker="sim", strategy="trend", equity=50, cash=50
        )
        self.ledger.record_order(
            run_id,
            broker_order_id="o1",
            symbol="SPY",
            side="buy",
            notional=5.0,
            qty=None,
            status="filled",
            fill_price=100.0,
        )
        maxed = Account("A1", "USD", 50, 50, 50, day_trade_count=2)
        veto = self.risk.check_exit("SPY", maxed)
        self.assertIsNotNone(veto)
        self.assertEqual(veto.code, "day_trade")

    def test_exit_allowed_when_not_bought_today(self):
        maxed = Account("A1", "USD", 50, 50, 50, day_trade_count=5)
        self.assertIsNone(self.risk.check_exit("SPY", maxed))


class TestLedger(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(os.path.join(self._tmp.name, "l.db"))

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def test_high_water_mark_ratchets_up_only(self):
        self.assertEqual(self.ledger.high_water_mark(50.0), 50.0)
        self.assertEqual(self.ledger.high_water_mark(60.0), 60.0)
        self.assertEqual(self.ledger.high_water_mark(40.0), 60.0)

    def test_first_equity_today_is_the_earliest_sample(self):
        self.assertIsNone(self.ledger.first_equity_today())
        self.ledger.record_equity(50.0, 50.0)
        self.assertEqual(self.ledger.first_equity_today(), 50.0)

    def test_bought_today_tracks_symbols_independently(self):
        run_id = self.ledger.start_run(
            mode="t", broker="sim", strategy="trend", equity=50, cash=50
        )
        self.ledger.record_order(
            run_id,
            broker_order_id="o1",
            symbol="SPY",
            side="buy",
            notional=5.0,
            qty=None,
            status="filled",
            fill_price=1.0,
        )
        self.assertTrue(self.ledger.bought_today("SPY"))
        self.assertTrue(self.ledger.bought_today("spy"))
        self.assertFalse(self.ledger.bought_today("QQQ"))


class TestSimBroker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = temp_cfg(self._tmp.name)
        self.broker = SimBroker(self.cfg, starting_cash=50.0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_bars_are_deterministic(self):
        self.assertEqual(
            [b.close for b in synthetic_bars("SPY", 20)],
            [b.close for b in synthetic_bars("SPY", 20)],
        )

    def test_different_symbols_differ(self):
        self.assertNotEqual(
            [b.close for b in synthetic_bars("SPY", 20)],
            [b.close for b in synthetic_bars("QQQ", 20)],
        )

    def test_buy_then_sell_conserves_cash_when_price_is_unchanged(self):
        self.broker.submit_order("SPY", "buy", notional=10.0)
        self.assertAlmostEqual(self.broker.cash, 40.0, places=6)
        self.broker.close_position("SPY")
        self.assertAlmostEqual(self.broker.cash, 50.0, places=4)
        self.assertEqual(self.broker.get_positions(), [])

    def test_cannot_overspend(self):
        with self.assertRaises(BrokerError):
            self.broker.submit_order("SPY", "buy", notional=999.0)

    def test_order_needs_exactly_one_of_qty_or_notional(self):
        with self.assertRaises(BrokerError):
            self.broker.submit_order("SPY", "buy")
        with self.assertRaises(BrokerError):
            self.broker.submit_order("SPY", "buy", notional=5.0, qty=1.0)

    def test_selling_nothing_raises(self):
        with self.assertRaises(BrokerError):
            self.broker.close_position("SPY")


class TestEngine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = temp_cfg(
            self._tmp.name, universe=["SPY", "QQQ", "IWM", "DIA", "VTI"]
        )
        self.ledger = Ledger(self.cfg.db_path)
        self.broker = SimBroker(self.cfg, starting_cash=50.0)
        self.engine = Engine(self.cfg, broker=self.broker, ledger=self.ledger)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def test_dry_run_places_no_orders(self):
        report = self.engine.cycle(dry_run=True)
        self.assertFalse(report.traded)
        self.assertEqual(self.broker.orders, [])
        self.assertEqual(self.ledger.orders_today(), 0)

    def test_cycle_is_idempotent_within_a_process(self):
        first = self.engine.cycle()
        opened = {a.symbol for a in first.actions if a.executed and a.intent == "enter"}
        self.assertTrue(opened, "expected the sim universe to produce at least one entry")

        second = self.engine.cycle()
        reopened = {a.symbol for a in second.actions if a.executed and a.intent == "enter"}
        self.assertEqual(reopened, set(), "second cycle must not re-buy an open position")

    def test_never_exceeds_max_positions(self):
        for _ in range(5):
            self.engine.cycle()
        self.assertLessEqual(
            len(self.broker.get_positions()), self.cfg.limits.max_positions
        )

    def test_never_exceeds_the_deployment_cap(self):
        for _ in range(5):
            self.engine.cycle()
        deployed = sum(p.market_value for p in self.broker.get_positions())
        self.assertLessEqual(deployed, self.cfg.limits.max_deployed + 0.01)

    def test_halt_file_prevents_all_trading(self):
        Path(self.cfg.halt_file).write_text("stop")
        report = self.engine.cycle()
        self.assertTrue(report.halted)
        self.assertFalse(report.traded)
        self.assertEqual(self.broker.orders, [])

    def test_closed_market_prevents_trading(self):
        self.broker.market_open = False
        report = self.engine.cycle()
        self.assertFalse(report.traded)
        self.assertEqual(self.broker.orders, [])

    def test_live_mode_without_confirmation_places_no_orders(self):
        cfg = temp_cfg(
            self._tmp.name,
            broker="alpaca",  # would be real money...
            alpaca_env="live",
            live_confirm="ok fine",  # ...but the phrase is wrong
            universe=["SPY"],
        )
        broker = SimBroker(cfg, starting_cash=50.0)  # stand-in, must stay untouched
        engine = Engine(cfg, broker=broker, ledger=self.ledger)
        report = engine.cycle()
        self.assertIn("live_unarmed", {v.code for v in report.halted})
        self.assertEqual(broker.orders, [])

    def test_held_symbol_outside_the_universe_is_still_evaluated(self):
        self.broker.submit_order("ZZZ", "buy", notional=5.0)
        report = self.engine.cycle()
        self.assertIn("ZZZ", {a.symbol for a in report.actions})

    def test_decisions_are_journalled_even_when_nothing_trades(self):
        self.engine.cycle(dry_run=True)
        rows = self.ledger._conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()
        self.assertGreater(rows["n"], 0)


class TestBacktest(unittest.TestCase):
    def test_backtest_runs_and_conserves_plausibility(self):
        bars = {symbol: synthetic_bars(symbol, 500) for symbol in ("SPY", "QQQ", "IWM")}
        result = run_backtest(bars, strategy.TrendStrategy(), starting_equity=50.0)
        self.assertEqual(result.starting_equity, 50.0)
        self.assertGreater(len(result.equity_curve), 0)
        self.assertGreaterEqual(result.max_drawdown_pct, 0.0)
        self.assertGreater(result.final_equity, 0.0)

    def test_backtest_rejects_too_little_history(self):
        bars = {"SPY": synthetic_bars("SPY", 30)}
        with self.assertRaises(ValueError):
            run_backtest(bars, strategy.TrendStrategy())

    def test_costs_reduce_returns(self):
        bars = {symbol: synthetic_bars(symbol, 500) for symbol in ("SPY", "QQQ")}
        cheap = run_backtest(bars, strategy.TrendStrategy(), cost_bps=0.0)
        pricey = run_backtest(bars, strategy.TrendStrategy(), cost_bps=100.0)
        self.assertGreaterEqual(cheap.final_equity, pricey.final_equity)


class TestStopBook(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(os.path.join(self._tmp.name, "s.db"))
        self.stops = StopBook(self.ledger)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def test_open_position_records_the_stop(self):
        state = self.stops.open_position("SPY", entry_price=100.0, stop_price=90.0)
        self.assertEqual(state.stop_price, 90.0)
        self.assertEqual(self.stops.get("SPY").stop_price, 90.0)

    def test_stop_ratchets_up_with_price(self):
        self.stops.open_position("SPY", 100.0, 90.0)
        state = self.stops.update("SPY", price=120.0, candidate_stop=108.0)
        self.assertEqual(state.stop_price, 108.0)
        self.assertEqual(state.high_water, 120.0)

    def test_stop_never_loosens_when_price_falls(self):
        self.stops.open_position("SPY", 100.0, 90.0)
        self.stops.update("SPY", price=120.0, candidate_stop=108.0)
        # Price collapses; the strategy's fresh ATR stop is far lower.
        state = self.stops.update("SPY", price=95.0, candidate_stop=85.0)
        self.assertEqual(state.stop_price, 108.0, "stop must never move down")
        self.assertEqual(state.high_water, 120.0, "high-water must not reset")

    def test_candidate_above_current_price_is_rejected(self):
        self.stops.open_position("SPY", 100.0, 90.0)
        state = self.stops.update("SPY", price=100.0, candidate_stop=105.0)
        self.assertEqual(state.stop_price, 90.0)

    def test_breach_detection(self):
        state = self.stops.open_position("SPY", 100.0, 90.0)
        self.assertFalse(state.breached(90.01))
        self.assertTrue(state.breached(90.0))
        self.assertTrue(state.breached(88.0))
        self.assertFalse(state.breached(0.0), "a missing price is not a breach")

    def test_untracked_position_is_adopted_rather_than_left_naked(self):
        state = self.stops.update("QQQ", price=50.0, candidate_stop=45.0)
        self.assertIsNotNone(state)
        self.assertEqual(state.stop_price, 45.0)

    def test_adopted_position_without_candidate_gets_a_default_stop(self):
        state = self.stops.update("QQQ", price=50.0, candidate_stop=None)
        self.assertLess(state.stop_price, 50.0)

    def test_sync_prunes_positions_no_longer_held(self):
        self.stops.open_position("SPY", 100.0, 90.0)
        self.stops.open_position("QQQ", 200.0, 180.0)
        self.stops.sync({"SPY"})
        self.assertIsNotNone(self.stops.get("SPY"))
        self.assertIsNone(self.stops.get("QQQ"))

    def test_trail_fraction_is_captured_at_entry(self):
        state = self.stops.open_position("SPY", entry_price=100.0, stop_price=90.0)
        self.assertAlmostEqual(state.trail_fraction, 0.10, places=6)

    def test_stop_trails_the_high_water_price(self):
        self.stops.open_position("SPY", entry_price=100.0, stop_price=90.0)  # 10% trail
        state = self.stops.update("SPY", price=200.0, candidate_stop=None)
        self.assertAlmostEqual(state.stop_price, 180.0, places=6)

    def test_trailing_stop_rises_above_entry_locking_in_gains(self):
        self.stops.open_position("SPY", entry_price=100.0, stop_price=90.0)
        state = self.stops.update("SPY", price=150.0, candidate_stop=None)
        self.assertGreater(state.stop_price, 100.0)

    def test_trailing_stop_is_never_placed_at_or_above_current_price(self):
        self.stops.open_position("SPY", entry_price=100.0, stop_price=99.9)
        state = self.stops.update("SPY", price=100.0, candidate_stop=None)
        self.assertLess(state.stop_price, 100.0)

    def test_trail_takes_the_highest_of_the_candidates(self):
        self.stops.open_position("SPY", entry_price=100.0, stop_price=90.0)
        # High-water trail implies 108; the strategy's ATR stop implies 95.
        state = self.stops.update("SPY", price=120.0, candidate_stop=95.0)
        self.assertAlmostEqual(state.stop_price, 108.0, places=6)

    def test_nonsensical_stop_is_rejected_not_stored(self):
        for bad in (-311.0, 0.0, 150.0):
            state = self.stops.open_position("SPY", entry_price=100.0, stop_price=bad)
            self.assertGreater(state.stop_price, 0)
            self.assertLess(state.stop_price, 100.0)
            self.assertLessEqual(state.trail_fraction, 0.90)

    def test_state_survives_a_new_book_over_the_same_ledger(self):
        self.stops.open_position("SPY", 100.0, 90.0)
        self.assertEqual(StopBook(self.ledger).get("SPY").stop_price, 90.0)


class TestStopEnforcement(unittest.TestCase):
    """The behaviour that matters with real money: stops actually fire."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = temp_cfg(self._tmp.name, universe=["SPY", "QQQ", "IWM", "DIA", "VTI"])
        self.ledger = Ledger(self.cfg.db_path)
        self.broker = SimBroker(self.cfg, starting_cash=50.0)
        self.engine = Engine(self.cfg, broker=self.broker, ledger=self.ledger)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def _open_one(self) -> str:
        report = self.engine.cycle()
        opened = [a.symbol for a in report.actions if a.executed and a.intent == "enter"]
        self.assertTrue(opened, "test needs at least one opened position")
        return opened[0]

    def test_entry_records_a_stop(self):
        symbol = self._open_one()
        state = self.engine.stops.get(symbol)
        self.assertIsNotNone(state, "an entry must record its stop")
        self.assertGreater(state.stop_price, 0)
        self.assertLess(state.stop_price, state.entry_price)

    def test_entry_arms_a_resting_broker_side_stop(self):
        symbol = self._open_one()
        resting = self.broker.list_open_orders(symbol)
        self.assertEqual(len(resting), 1)
        self.assertTrue(resting[0].is_protective)
        self.assertAlmostEqual(
            resting[0].stop_price, self.engine.stops.get(symbol).stop_price, places=6
        )

    def test_price_below_stop_forces_an_exit(self):
        symbol = self._open_one()
        state = self.engine.stops.get(symbol)
        self.broker.price_overrides[symbol] = state.stop_price * 0.95

        report = self.engine.cycle()
        exits = [a for a in report.actions if a.intent == "exit" and a.executed]
        self.assertEqual([a.symbol for a in exits], [symbol])
        self.assertIn("STOP HIT", exits[0].reason)
        self.assertEqual(self.broker.get_positions(), [])

    def test_stop_exit_clears_the_stop_book_and_resting_orders(self):
        symbol = self._open_one()
        self.broker.price_overrides[symbol] = self.engine.stops.get(symbol).stop_price * 0.9
        self.engine.cycle()
        self.assertIsNone(self.engine.stops.get(symbol))
        self.assertEqual(self.broker.list_open_orders(symbol), [])

    def test_stop_overrides_the_day_trade_guard(self):
        """A PDT flag is bad; an unstopped loss is worse."""
        symbol = self._open_one()
        state = self.engine.stops.get(symbol)
        self.broker.price_overrides[symbol] = state.stop_price * 0.9

        # Force the day-trade guard to be maximally hostile.
        original = self.engine.broker.get_account

        def maxed_out():
            account = original()
            return Account(
                account.account_id,
                account.currency,
                account.cash,
                account.equity,
                account.buying_power,
                day_trade_count=99,
            )

        self.engine.broker.get_account = maxed_out
        report = self.engine.cycle()
        self.assertTrue(
            any(a.executed and a.intent == "exit" for a in report.actions),
            "stop breach must not be blocked by the day-trade guard",
        )

    def test_ordinary_exit_still_respects_the_day_trade_guard(self):
        run_id = self.ledger.start_run(
            mode="t", broker="sim", strategy="trend", equity=50, cash=50
        )
        self.ledger.record_order(
            run_id, broker_order_id="o1", symbol="SPY", side="buy",
            notional=5.0, qty=None, status="filled", fill_price=1.0,
        )
        maxed = Account("A1", "USD", 50, 50, 50, day_trade_count=99)
        self.assertIsNotNone(self.engine.risk.check_exit("SPY", maxed))

    def test_every_open_position_ends_the_cycle_with_a_usable_stop(self):
        for _ in range(3):
            self.engine.cycle()
        for position in self.broker.get_positions():
            state = self.engine.stops.get(position.symbol)
            self.assertIsNotNone(state, f"{position.symbol} has no stop")
            self.assertGreater(state.stop_price, 0)
            self.assertLess(state.stop_price, self.broker.latest_price(position.symbol) * 1.5)

    def test_a_corrupted_stop_is_repaired_on_the_next_cycle(self):
        symbol = self._open_one()
        # Simulate the old bug: a stored stop of zero, i.e. no protection.
        self.engine.stops._ledger.set_state(
            "stops", {symbol: {"symbol": symbol, "entry_price": 10.0,
                               "stop_price": 0.0, "high_water": 10.0,
                               "trail_fraction": 0.1}})
        self.engine.cycle()
        repaired = self.engine.stops.get(symbol)
        self.assertIsNotNone(repaired)
        self.assertGreater(repaired.stop_price, 0, "the cycle must repair a zeroed stop")
        self.assertLess(repaired.stop_price, self.broker.latest_price(symbol))

    def test_an_unprotected_position_is_reported_loudly(self):
        """When a stop cannot be established at all, say so — never skip it."""
        symbol = self._open_one()
        self.engine.stops.close(symbol)  # no stop on file at all
        report = CycleReport(
            started_at=datetime.now(timezone.utc), mode="sim",
            broker_name="sim", strategy_name="trend",
        )
        run_id = self.ledger.start_run(
            mode="t", broker="sim", strategy="trend", equity=50, cash=50
        )
        self.engine._arm_protective_stops(report, run_id)
        self.assertTrue(
            any("unprotected" in (a.blocked_by or "").lower() for a in report.actions),
            "a position with no usable stop must be surfaced, not skipped silently",
        )

    def test_price_above_stop_does_not_exit(self):
        symbol = self._open_one()
        state = self.engine.stops.get(symbol)
        self.broker.price_overrides[symbol] = state.stop_price * 1.10
        report = self.engine.cycle()
        self.assertFalse(
            any(a.executed and a.intent == "exit" and a.symbol == symbol for a in report.actions)
        )

    def test_dry_run_arms_nothing_and_sends_nothing(self):
        report = self.engine.cycle(dry_run=True)
        self.assertEqual(self.broker.open_orders, [])
        self.assertEqual(report.protective_stops, [])

    def test_protective_stops_do_not_consume_the_daily_order_budget(self):
        before = self.ledger.orders_today()
        self._open_one()
        # One buy counts; the protective stop that follows must not.
        self.assertEqual(self.ledger.orders_today(), before + 1)

    def test_repeated_cycles_do_not_pile_up_resting_orders(self):
        symbol = self._open_one()
        for _ in range(4):
            self.engine.cycle()
        self.assertEqual(
            len(self.broker.list_open_orders(symbol)), 1,
            "each cycle must cancel the old stop before arming a new one",
        )

    def test_stop_trails_up_then_exits_with_a_profit(self):
        symbol = self._open_one()
        entry = self.engine.stops.get(symbol).entry_price

        self.broker.price_overrides[symbol] = entry * 1.30
        self.engine.cycle()
        trailed = self.engine.stops.get(symbol)
        self.assertGreater(trailed.stop_price, entry, "stop should be above entry after a 30% run")

        self.broker.price_overrides[symbol] = trailed.stop_price * 0.99
        report = self.engine.cycle()
        self.assertTrue(any(a.executed and a.intent == "exit" for a in report.actions))
        self.assertGreater(
            self.broker.get_account().equity, 50.0,
            "a trailing stop that fires above entry must bank a gain",
        )

    def test_breach_message_reports_the_live_price_not_the_bar_close(self):
        symbol = self._open_one()
        state = self.engine.stops.get(symbol)
        breach_price = state.stop_price * 0.90
        self.broker.price_overrides[symbol] = breach_price
        report = self.engine.cycle()
        exit_action = next(a for a in report.actions if a.executed and a.intent == "exit")
        self.assertIn(f"{breach_price:.2f}", exit_action.reason)

    def test_stop_is_checked_against_live_price_not_the_stale_close(self):
        symbol = self._open_one()
        state = self.engine.stops.get(symbol)
        # Bars still show the old close; only the live price has collapsed.
        self.broker.price_overrides[symbol] = state.stop_price * 0.5
        report = self.engine.cycle()
        self.assertTrue(
            any(a.executed and a.intent == "exit" and a.symbol == symbol for a in report.actions)
        )


# ---------------------------------------------------------------------------
# Kraken adapter, exercised against a fake HTTP layer (no network).
# ---------------------------------------------------------------------------

ASSET_PAIRS = {
    "XXBTZEUR": {
        "altname": "XBTEUR", "wsname": "XBT/EUR",
        "base": "XXBT", "quote": "ZEUR",
        "lot_decimals": 8, "pair_decimals": 1,
        "ordermin": "0.00005", "costmin": "0.5",
    },
    "XETHZEUR": {
        "altname": "ETHEUR", "wsname": "ETH/EUR",
        "base": "XETH", "quote": "ZEUR",
        "lot_decimals": 8, "pair_decimals": 2,
        "ordermin": "0.002", "costmin": "0.5",
    },
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeKrakenSession:
    """Canned Kraken responses; records every request for assertions."""

    def __init__(self, **overrides):
        self.headers = {}
        self.calls = []
        self.posts = []
        self.overrides = overrides
        self.btc_balance = "0.1"

    def _payload(self, path):
        if path in self.overrides:
            return self.overrides[path]
        if path.endswith("/AssetPairs"):
            return {"error": [], "result": ASSET_PAIRS}
        if path.endswith("/OHLC"):
            rows = [
                [1700000000 + i * 86400, "100", "110", "90", str(100 + i), "0", "5", 10]
                for i in range(30)
            ]
            return {"error": [], "result": {"XXBTZEUR": rows, "last": 1}}
        if path.endswith("/Ticker"):
            return {"error": [], "result": {"XXBTZEUR": {"c": ["100.0", "0.1"]}}}
        if path.endswith("/SystemStatus"):
            return {"error": [], "result": {"status": "online"}}
        if path.endswith("/Balance"):
            return {"error": [], "result": {"ZEUR": "50.0", "XXBT": self.btc_balance}}
        if path.endswith("/TradeBalance"):
            return {"error": [], "result": {"eb": "55.0"}}
        if path.endswith("/AddOrder"):
            return {"error": [], "result": {"txid": ["OABC-123"]}}
        if path.endswith("/OpenOrders"):
            return {"error": [], "result": {"open": {"OXYZ-1": {
                "descr": {"pair": "XBTEUR", "type": "sell",
                          "ordertype": "stop-loss", "price": "90.0"},
                "vol": "0.001", "status": "open"}}}}
        if path.endswith("/CancelOrder"):
            return {"error": [], "result": {"count": 1}}
        if path.endswith("/TradesHistory"):
            return {"error": [], "result": {"trades": {"T1": {
                "pair": "XXBTZEUR", "type": "buy", "vol": "0.001",
                "price": "80.0", "time": 1700000000}}}}
        return {"error": ["EGeneral:Unknown"], "result": {}}

    def _path(self, url):
        return url.replace("https://api.kraken.com", "")

    def get(self, url, params=None, timeout=None):
        path = self._path(url)
        self.calls.append(path)
        return FakeResponse(self._payload(path))

    def post(self, url, data=None, headers=None, timeout=None):
        path = self._path(url)
        self.calls.append(path)
        self.posts.append((path, dict(data or {}), dict(headers or {})))
        return FakeResponse(self._payload(path))


def kraken_cfg(**overrides):
    defaults = dict(
        broker="kraken",
        kraken_key="testkey",
        kraken_secret=base64.b64encode(b"secret-material").decode(),
        quote_currency="EUR",
        universe=["XBTEUR"],
        live_confirm=LIVE_CONFIRM_PHRASE,
        limits=Limits(),
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestKrakenAdapter(unittest.TestCase):
    def setUp(self):
        self.session = FakeKrakenSession()
        self.broker = KrakenBroker(kraken_cfg(), session=self.session)

    def test_kraken_is_always_real_money(self):
        self.assertTrue(kraken_cfg().is_real_money)
        self.assertFalse(kraken_cfg(live_confirm="").is_live)
        self.assertTrue(kraken_cfg(live_confirm="").live_requested_but_unarmed)

    def test_signing_sets_headers_and_increments_the_nonce(self):
        self.broker.get_account()
        private = [p for p in self.session.posts if "private" in p[0]]
        self.assertTrue(private)
        _path, body, headers = private[0]
        self.assertEqual(headers["API-Key"], "testkey")
        self.assertIn("API-Sign", headers)
        self.assertIn("nonce", body)

        first = int(private[0][1]["nonce"])
        self.broker.get_account()
        second = int([p for p in self.session.posts if "private" in p[0]][-1][1]["nonce"])
        self.assertGreater(second, first)

    def test_malformed_secret_is_reported_clearly(self):
        broker = KrakenBroker(kraken_cfg(kraken_secret="not!base64!"), session=self.session)
        with self.assertRaises(BrokerError) as ctx:
            broker.get_account()
        self.assertIn("base64", str(ctx.exception))

    def test_pair_resolution_accepts_every_alias(self):
        for alias in ("XBTEUR", "xbteur", "XXBTZEUR", "XBT/EUR"):
            self.assertEqual(self.broker._pair(alias)["_key"], "XXBTZEUR")

    def test_unknown_pair_raises_a_helpful_error(self):
        with self.assertRaises(BrokerError) as ctx:
            self.broker._pair("SPY")
        self.assertIn("XBTEUR", str(ctx.exception))

    def test_bars_are_parsed_and_sorted_oldest_first(self):
        bars = self.broker.get_daily_bars("XBTEUR", 10)
        self.assertEqual(len(bars), 10)
        self.assertEqual([b.day for b in bars], sorted(b.day for b in bars))
        self.assertEqual(bars[-1].close, 129.0)

    def test_account_uses_eur_and_trade_balance(self):
        account = self.broker.get_account()
        self.assertEqual(account.currency, "EUR")
        self.assertEqual(account.cash, 50.0)
        self.assertEqual(account.equity, 55.0)
        self.assertEqual(account.day_trade_count, 0, "spot crypto has no PDT rule")

    def test_positions_are_derived_from_balances(self):
        positions = self.broker.get_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].symbol, "XBTEUR")
        self.assertAlmostEqual(positions[0].market_value, 10.0, places=6)

    def test_dust_balances_are_not_positions(self):
        self.session.btc_balance = "0.000001"  # worth 0.0001 EUR — dust
        self.assertEqual(self.broker.get_positions(), [])

    def test_average_entry_comes_from_trade_history(self):
        self.assertAlmostEqual(self.broker._average_entry("XBTEUR", 0.001), 80.0, places=6)

    def test_market_open_follows_system_status(self):
        self.assertTrue(self.broker.is_market_open())
        offline = KrakenBroker(
            kraken_cfg(),
            session=FakeKrakenSession(**{"/0/public/SystemStatus": {
                "error": [], "result": {"status": "maintenance"}}}),
        )
        self.assertFalse(offline.is_market_open())

    def test_notional_buy_converts_to_base_volume(self):
        order = self.broker.submit_order("XBTEUR", "buy", notional=10.0)
        self.assertAlmostEqual(order.qty, 0.1, places=8)  # 10 EUR / 100 EUR
        body = [p for p in self.session.posts if p[0].endswith("AddOrder")][0][1]
        self.assertEqual(body["type"], "buy")
        self.assertEqual(body["ordertype"], "market")

    def test_volume_is_rounded_down_never_up(self):
        # 3.55 EUR / 100 = 0.0355; at 3 lot decimals that must floor to 0.035,
        # spending 3.50 rather than rounding up past the cash on hand.
        broker = KrakenBroker(kraken_cfg(), session=FakeKrakenSession(
            **{"/0/public/AssetPairs": {"error": [], "result": {
                "XXBTZEUR": {**ASSET_PAIRS["XXBTZEUR"], "lot_decimals": 3}}}}))
        order = broker.submit_order("XBTEUR", "buy", notional=3.55)
        self.assertAlmostEqual(order.qty, 0.035, places=8)
        self.assertLessEqual(order.qty * 100.0, 3.55, "rounding must never overspend")

    def test_flooring_to_zero_is_refused_rather_than_sent(self):
        broker = KrakenBroker(kraken_cfg(), session=FakeKrakenSession(
            **{"/0/public/AssetPairs": {"error": [], "result": {
                "XXBTZEUR": {**ASSET_PAIRS["XXBTZEUR"], "lot_decimals": 1}}}}))
        with self.assertRaises(BrokerError):
            broker.submit_order("XBTEUR", "buy", notional=3.5)

    def test_order_below_pair_minimum_is_refused_locally(self):
        broker = KrakenBroker(kraken_cfg(), session=FakeKrakenSession(
            **{"/0/public/AssetPairs": {"error": [], "result": {
                "XXBTZEUR": {**ASSET_PAIRS["XXBTZEUR"], "ordermin": "1.0"}}}}))
        with self.assertRaises(BrokerError) as ctx:
            broker.submit_order("XBTEUR", "buy", notional=10.0)
        self.assertIn("minimum", str(ctx.exception))

    def test_order_below_cost_minimum_is_refused(self):
        broker = KrakenBroker(kraken_cfg(), session=FakeKrakenSession(
            **{"/0/public/AssetPairs": {"error": [], "result": {
                "XXBTZEUR": {**ASSET_PAIRS["XXBTZEUR"], "costmin": "25"}}}}))
        with self.assertRaises(BrokerError) as ctx:
            broker.submit_order("XBTEUR", "buy", notional=10.0)
        self.assertIn("below", str(ctx.exception))

    def test_pair_limits_are_exposed_for_preflight(self):
        ordermin, costmin = self.broker.pair_limits("XBTEUR")
        self.assertAlmostEqual(ordermin, 0.00005)
        self.assertAlmostEqual(costmin, 0.5)

    def test_stop_order_uses_stop_loss_type_and_pair_decimals(self):
        order = self.broker.submit_stop_order("XBTEUR", 0.001, 90.05)
        body = [p for p in self.session.posts if p[0].endswith("AddOrder")][0][1]
        self.assertEqual(body["ordertype"], "stop-loss")
        self.assertEqual(body["type"], "sell")
        # pair_decimals = 1, and the trigger is floored so it never lands
        # above the stop the risk layer asked for.
        self.assertEqual(body["price"], "90.0")
        self.assertLessEqual(float(body["price"]), 90.05)
        self.assertTrue(order.is_protective)

    def test_open_orders_are_recognised_as_protective(self):
        orders = self.broker.list_open_orders("XBTEUR")
        self.assertEqual(len(orders), 1)
        self.assertTrue(orders[0].is_protective)
        self.assertEqual(orders[0].stop_price, 90.0)

    def test_cancel_of_an_already_gone_order_is_not_an_error(self):
        broker = KrakenBroker(kraken_cfg(), session=FakeKrakenSession(
            **{"/0/private/CancelOrder": {"error": ["EOrder:Unknown order"], "result": {}}}))
        broker.cancel_order("OXYZ-1")  # must not raise

    def test_close_position_cancels_resting_orders_first(self):
        self.broker.close_position("XBTEUR")
        paths = [c for c in self.session.calls if "CancelOrder" in c or "AddOrder" in c]
        self.assertLess(paths.index([p for p in paths if "CancelOrder" in p][0]),
                        paths.index([p for p in paths if "AddOrder" in p][0]),
                        "must cancel the resting stop before selling")

    def test_invalid_key_produces_an_actionable_message(self):
        broker = KrakenBroker(kraken_cfg(), session=FakeKrakenSession(
            **{"/0/private/Balance": {"error": ["EAPI:Invalid key"], "result": {}}}))
        with self.assertRaises(BrokerError) as ctx:
            broker._balances()
        self.assertIn("KRAKEN_KEY", str(ctx.exception))

    def test_validate_flag_sends_no_real_order(self):
        self.broker.submit_order("XBTEUR", "buy", notional=10.0, validate=True)
        body = [p for p in self.session.posts if p[0].endswith("AddOrder")][0][1]
        self.assertEqual(body.get("validate"), "true")


if __name__ == "__main__":
    unittest.main()
