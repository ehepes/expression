"""Unit tests. Run with:  python -m unittest discover -s tests -v"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from agent import indicators, strategy
from agent.backtest import run_backtest
from agent.brokers.base import Account, Bar, BrokerError, Position
from agent.brokers.sim import SimBroker, synthetic_bars
from agent.config import LIVE_CONFIRM_PHRASE, Config, ConfigError, Limits
from agent.engine import Engine
from agent.ledger import Ledger
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


if __name__ == "__main__":
    unittest.main()
