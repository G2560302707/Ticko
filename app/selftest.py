# -*- coding: utf-8 -*-
"""离线自测：时长切分、跨日入账、心跳恢复、小时桶。"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as usage
import pet_packs
import sound_util
import window_space
sound_util.SILENT = True


class HourAndDateTests(unittest.TestCase):
    def test_hour_credits_simple(self):
        midnight = usage.next_midnight(time.time() - 1) - 86400
        buckets = usage.hour_credits(midnight + 3600, midnight + 3600 + 90, midnight)
        self.assertAlmostEqual(buckets[1], 90, places=5)
        self.assertEqual(sum(1 for x in buckets if x), 1)

    def test_hour_credits_cross_hour(self):
        midnight = usage.next_midnight(time.time() - 1) - 86400
        buckets = usage.hour_credits(midnight + 3500, midnight + 3700, midnight)
        self.assertAlmostEqual(buckets[0], 100, places=5)
        self.assertAlmostEqual(buckets[1], 100, places=5)

    def test_next_midnight_after(self):
        now = time.time()
        nxt = usage.next_midnight(now)
        self.assertGreater(nxt, now)
        self.assertLess(nxt - now, 86400 + 1)


class StorageTrackerTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = usage.Storage(self.path)

    def tearDown(self):
        try:
            self.store.conn.close()
        except Exception:
            pass
        try:
            os.remove(self.path)
        except Exception:
            pass
        for extra in (self.path + "-wal", self.path + "-shm"):
            try:
                os.remove(extra)
            except Exception:
                pass

    def test_midnight_split_credits_two_days(self):
        tracker = usage.Tracker.__new__(usage.Tracker)
        tracker.store = self.store
        tracker.cur = None
        tracker._finalized = False
        midnight = usage.next_midnight(time.time() - 3600)
        start = midnight - 20
        end = midnight + 40
        tracker._close({"app": "Code.exe", "state": "active", "start": start, "title": "x"}, end)
        d0 = usage.date_str(start)
        d1 = usage.date_str(end)
        self.assertNotEqual(d0, d1)
        r0 = self.store.read("SELECT active_seconds FROM daily_stats WHERE date=?", (d0,))
        r1 = self.store.read("SELECT active_seconds FROM daily_stats WHERE date=?", (d1,))
        self.assertAlmostEqual(r0[0][0], 20, places=3)
        self.assertAlmostEqual(r1[0][0], 40, places=3)

    def test_away_does_not_credit_app(self):
        tracker = usage.Tracker.__new__(usage.Tracker)
        tracker.store = self.store
        tracker._finalized = False
        now = time.time()
        tracker._close({"app": "Code.exe", "state": "away", "start": now - 10, "title": "x"}, now)
        apps = self.store.read("SELECT COUNT(*) FROM app_daily_stats")
        self.assertEqual(apps[0][0], 0)
        daily = self.store.read("SELECT away_seconds, system_seconds, active_seconds FROM daily_stats")
        self.assertAlmostEqual(daily[0][0], 10, places=3)
        self.assertAlmostEqual(daily[0][1], 10, places=3)
        self.assertEqual(daily[0][2], 0)

    def test_heartbeat_recover(self):
        now = time.time()
        self.store.save_open(now, {"app": "a.exe", "state": "active", "start": now - 15, "title": "t"})
        tracker = usage.Tracker(self.store)
        self.assertIsNone(tracker.cur)
        row = self.store.read("SELECT active_seconds FROM daily_stats")
        self.assertAlmostEqual(row[0][0], 15, places=2)

    def test_need_split_rules(self):
        # active + app change splits; away + app change does not
        cur_away = {"app": "a.exe", "state": "away"}
        state, app = "away", "b.exe"
        need = (state != cur_away["state"]) or (state == "active" and app != cur_away["app"])
        self.assertFalse(need)
        cur_act = {"app": "a.exe", "state": "active"}
        state, app = "active", "b.exe"
        need = (state != cur_act["state"]) or (state == "active" and app != cur_act["app"])
        self.assertTrue(need)

    def test_ignored_app_skips_ranking_keeps_clocks(self):
        tracker = usage.Tracker.__new__(usage.Tracker)
        tracker.store = self.store
        tracker._finalized = False
        self.store.save_ignore_config(["explorer.exe"], 5)
        now = time.time()
        tracker._close(
            {"app": "explorer.exe", "state": "active", "start": now - 20, "title": "x", "category": "系统"},
            now,
        )
        apps = self.store.read("SELECT COUNT(*) FROM app_daily_stats")
        self.assertEqual(apps[0][0], 0)
        cats = self.store.read("SELECT COUNT(*) FROM category_daily_stats")
        self.assertEqual(cats[0][0], 0)
        daily = self.store.read("SELECT active_seconds, system_seconds FROM daily_stats")
        self.assertAlmostEqual(daily[0][0], 20, places=3)
        self.assertAlmostEqual(daily[0][1], 20, places=3)

    def test_short_flash_skips_app_stats(self):
        tracker = usage.Tracker.__new__(usage.Tracker)
        tracker.store = self.store
        tracker._finalized = False
        self.store.save_ignore_config(["ticko.exe"], 5)
        now = time.time()
        tracker._close(
            {"app": "chrome.exe", "state": "active", "start": now - 3, "title": "x", "category": "娱乐"},
            now,
        )
        apps = self.store.read("SELECT COUNT(*) FROM app_daily_stats")
        self.assertEqual(apps[0][0], 0)
        daily = self.store.read("SELECT active_seconds FROM daily_stats")
        self.assertAlmostEqual(daily[0][0], 3, places=3)


class IgnoreAndGoalsTests(unittest.TestCase):
    def test_should_credit_defaults(self):
        import goals_util
        cfg = goals_util.normalize_ignore_config()
        self.assertFalse(goals_util.should_credit_app("explorer.exe", 30, cfg))
        self.assertFalse(goals_util.should_credit_app("Ticko.exe", 30, cfg))
        self.assertFalse(goals_util.should_credit_app("chrome.exe", 3, cfg))
        self.assertTrue(goals_util.should_credit_app("chrome.exe", 20, cfg))

    def test_empty_ignore_list_is_honored(self):
        import goals_util
        cfg = goals_util.normalize_ignore_config([], 5, apps_missing=False)
        self.assertEqual(cfg["apps"], [])
        self.assertTrue(goals_util.should_credit_app("explorer.exe", 20, cfg))

    def test_goals_progress_min_max(self):
        import goals_util
        goals = goals_util.normalize_daily_goals({
            "active": {"min": 28800, "max": None},
            "categories": {"娱乐": {"min": None, "max": 7200}, "学习": {"min": 10800}},
        })
        items = goals_util.goals_progress(14400, {"娱乐": 8000, "学习": 10800}, goals)
        by_id = {x["id"]: x for x in items}
        self.assertEqual(by_id["active-min"]["status"], "ok")
        self.assertEqual(by_id["cat-max-娱乐"]["status"], "over")
        self.assertEqual(by_id["cat-min-学习"]["status"], "done")
        near = goals_util.goals_progress(27000, {}, {"active": {"min": 28800}})
        self.assertEqual(near[0]["status"], "near")


class DurationParseTests(unittest.TestCase):
    def test_parse_and_format(self):
        import goals_util
        self.assertIsNone(goals_util.parse_duration_text(""))
        self.assertIsNone(goals_util.parse_duration_text("  "))
        self.assertEqual(goals_util.parse_duration_text("90"), 90 * 60)
        self.assertEqual(goals_util.parse_duration_text("90m"), 90 * 60)
        self.assertEqual(goals_util.parse_duration_text("90分"), 90 * 60)
        self.assertEqual(goals_util.parse_duration_text("1:30"), 90 * 60)
        self.assertEqual(goals_util.parse_duration_text("1h30"), 90 * 60)
        self.assertEqual(goals_util.parse_duration_text("1h30m"), 90 * 60)
        self.assertEqual(goals_util.parse_duration_text("1小时30分"), 90 * 60)
        self.assertEqual(goals_util.parse_duration_text("1.5h"), 90 * 60)
        self.assertEqual(goals_util.parse_duration_text("1.5"), 90 * 60)
        self.assertEqual(goals_util.format_duration_short(90 * 60), "1小时30分")
        self.assertEqual(goals_util.format_duration_short(45 * 60), "45分")
        self.assertEqual(goals_util.format_duration_short(8 * 3600), "8小时")
        self.assertEqual(goals_util.format_duration_short(None), "")

    def test_step_five_minutes(self):
        import goals_util
        self.assertEqual(goals_util.step_duration(90 * 60, 5), 95 * 60)
        self.assertEqual(goals_util.step_duration(None, 5), 5 * 60)
        self.assertEqual(goals_util.step_duration(2 * 60, -5), 0)


class PomodoroTests(unittest.TestCase):
    def tearDown(self):
        import pomodoro_util
        pomodoro_util.stop(now=0)

    def test_focus_then_break(self):
        import pomodoro_util
        t0 = 1_000_000.0
        pomodoro_util.start(1, 1, now=t0)
        snap = pomodoro_util.snapshot(now=t0)
        self.assertEqual(snap["mode"], "focus")
        self.assertEqual(snap["remain"], 60)
        self.assertIn("专注", pomodoro_util.format_overlay(snap))
        evt = pomodoro_util.tick(now=t0 + 61)
        self.assertEqual(evt, "focus_done")
        snap = pomodoro_util.snapshot(now=t0 + 61)
        self.assertEqual(snap["mode"], "break")
        evt = pomodoro_util.tick(now=t0 + 122)
        self.assertEqual(evt, "break_done")
        self.assertEqual(pomodoro_util.snapshot(now=t0 + 122)["mode"], "idle")

    def test_pause_and_resume(self):
        import pomodoro_util
        t0 = 2_000_000.0
        pomodoro_util.start(25, 5, now=t0)
        pomodoro_util.toggle_pause(now=t0 + 10)
        self.assertEqual(pomodoro_util.snapshot(now=t0 + 40)["mode"], "paused")
        self.assertEqual(pomodoro_util.snapshot(now=t0 + 40)["remain"], 25 * 60 - 10)
        pomodoro_util.toggle_pause(now=t0 + 40)
        self.assertEqual(pomodoro_util.snapshot(now=t0 + 40)["mode"], "focus")

    def test_start_seconds_and_simulate(self):
        import pomodoro_util
        t0 = 3_000_000.0
        pomodoro_util.start(focus_sec=5, break_sec=5, now=t0)
        self.assertEqual(pomodoro_util.snapshot(now=t0)["remain"], 5)
        evt = pomodoro_util.tick(now=t0 + 6)
        self.assertEqual(evt, "focus_done")
        snap = pomodoro_util.simulate("break_done")
        self.assertEqual(snap["last_event"], "break_done")
        self.assertEqual(pomodoro_util.take_speech_event(), "break_done")
        self.assertIsNone(pomodoro_util.take_speech_event())


class SoundUtilTests(unittest.TestCase):
    # 隔离：测试期间所有音效读写都指向系统临时目录，绝不触碰真实 data/。
    def setUp(self):
        import tempfile
        # 临时目录创建在系统 temp（非项目目录），符合“禁止在项目目录创建临时目录”。
        self._tmp = tempfile.mkdtemp(prefix="ticko_sound_test_")
        self._real_builtin = sound_util.BUILTIN_DIR
        self._real_custom = sound_util.CUSTOM_DIR
        sound_util.BUILTIN_DIR = os.path.join(self._tmp, "builtin")
        sound_util.CUSTOM_DIR = os.path.join(self._tmp, "custom")

    def tearDown(self):
        # 不论成功/失败/异常，都还原真实路径并清理临时目录。
        import shutil
        if getattr(self, "_real_builtin", None) is not None:
            sound_util.BUILTIN_DIR = self._real_builtin
        if getattr(self, "_real_custom", None) is not None:
            sound_util.CUSTOM_DIR = self._real_custom
        if getattr(self, "_tmp", None) is not None and os.path.isdir(self._tmp):
            shutil.rmtree(self._tmp, ignore_errors=True)
        self._tmp = None

    def test_defaults_and_upload(self):
        import sound_util
        sound_util.ensure_defaults()
        data = sound_util.list_sounds()
        ids = [x["id"] for x in data["items"]]
        self.assertIn("chime", ids)
        self.assertIn("wood", ids)
        self.assertIn("ping", ids)
        self.assertIn("urgent", ids)
        path = sound_util.resolve_path("chime")
        self.assertTrue(path and os.path.isfile(path))
        self.assertGreater(os.path.getsize(path), 200)
        sid, err = sound_util.save_upload("mine.wav", b"RIFF" + b"\x00" * 64)
        self.assertIsNone(err)
        self.assertTrue(sound_util.resolve_path(sid))
        self.assertTrue(sound_util.delete_custom(sid))
        self.assertIsNone(sound_util.resolve_path(sid))


class PetHookTests(unittest.TestCase):
    def tearDown(self):
        usage.register_pet_hooks(None, None)

    def test_apply_pet_visibility_calls_hooks(self):
        calls = []
        usage.register_pet_hooks(lambda: calls.append("show"), lambda: calls.append("hide"))
        self.assertTrue(usage.apply_pet_visibility(False))
        self.assertTrue(usage.apply_pet_visibility(True))
        self.assertEqual(calls, ["hide", "show"])
        usage.register_pet_hooks(None, None)
        self.assertFalse(usage.apply_pet_visibility(True))

    def test_apply_pet_settings_calls_settings_hook(self):
        calls = []
        usage.register_pet_hooks(None, None, lambda data: calls.append(data))
        self.assertTrue(usage.apply_pet_settings({"pet_mode": "still"}))
        self.assertEqual(calls, [{"pet_mode": "still"}])


class ClassifyTests(unittest.TestCase):
    def test_bilibili_learn_vs_fun(self):
        import classify
        self.assertEqual(
            classify.classify("chrome.exe", "Python零基础教程_哔哩哔哩_bilibili"),
            "学习",
        )
        self.assertEqual(
            classify.classify("msedge.exe", "搞笑配音_哔哩哔哩_bilibili"),
            "娱乐",
        )

    def test_rain_classroom_is_learn(self):
        import classify
        self.assertEqual(classify.classify("chrome.exe", "高等数学 - 雨课堂"), "学习")
        self.assertEqual(classify.classify("msedge.exe", "Rain Classroom"), "学习")
        self.assertEqual(classify.classify("chrome.exe", "线性代数 第3次课 - yuketang"), "学习")

    def test_chaoxing_and_mooc_are_learn(self):
        import classify
        self.assertEqual(classify.classify("chrome.exe", "大学物理 - 超星学习通"), "学习")
        self.assertEqual(classify.classify("firefox.exe", "中国大学MOOC - 电路分析"), "学习")

    def test_bilibili_subject_without_教程(self):
        import classify
        self.assertEqual(
            classify.classify("chrome.exe", "【考研数学】高数全程班_哔哩哔哩_bilibili"),
            "学习",
        )
        self.assertEqual(
            classify.classify("chrome.exe", "线性代数 李永乐_哔哩哔哩_bilibili"),
            "学习",
        )
        self.assertEqual(
            classify.classify("bilibili.exe", "英语四级真题精讲"),
            "学习",
        )

    def test_game_guide_stays_fun(self):
        import classify
        self.assertEqual(
            classify.classify("chrome.exe", "原神萌新教程_哔哩哔哩_bilibili"),
            "娱乐",
        )

    def test_builtin_lexicon_size(self):
        import classify_words
        self.assertGreaterEqual(len(classify_words.LEARN_WORDS), 300)
        self.assertGreaterEqual(len(classify_words.LEARN_SITES), 30)
        self.assertIn("雨课堂", classify_words.LEARN_WORDS)
        self.assertIn("高数", classify_words.LEARN_WORDS)

    def test_user_extra_words_merge(self):
        import classify
        rules = classify.normalize_rules({"learn_words": ["我的私教课"]})
        self.assertEqual(classify.classify("chrome.exe", "我的私教课 - 标签", rules), "学习")
        self.assertEqual(classify.classify("chrome.exe", "雨课堂", rules), "学习")
        editor = classify.editor_rules({"learn_words": ["我的私教课", "教程"]})
        self.assertEqual(editor["learn_words"], ["我的私教课"])
        self.assertGreaterEqual(editor["builtin"]["learn_words"], 300)

    def test_vscode_work(self):
        import classify
        self.assertEqual(classify.classify("Code.exe", "app.py - Visual Studio Code"), "工作")

    def test_browser_defaults_to_entertainment(self):
        import classify
        self.assertEqual(classify.classify("chrome.exe", "某个普通网页 - Google Chrome"), "娱乐")
        self.assertEqual(classify.classify("msedge.exe", "新闻 - Microsoft Edge"), "娱乐")
        self.assertEqual(classify.classify("bilibili.exe", "追番"), "娱乐")
        self.assertEqual(classify.classify("ApplicationFrameHost.exe", "搞笑配音_哔哩哔哩_bilibili"), "娱乐")

    def test_browser_work_and_learn_titles(self):
        import classify
        self.assertEqual(classify.classify("chrome.exe", "飞书 - 文档"), "工作")
        self.assertEqual(classify.classify("chrome.exe", "Python零基础教程"), "学习")
        self.assertEqual(classify.classify("chrome.exe", "GitHub"), "学习")


class BreakdownTests(unittest.TestCase):
    def test_groups_apps_and_titles(self):
        segs = [
            {"state": "active", "category": "娱乐", "app": "chrome.exe", "title": "番剧_哔哩哔哩", "start": 0, "end": 40},
            {"state": "active", "category": "娱乐", "app": "chrome.exe", "title": "音乐", "start": 40, "end": 70},
            {"state": "active", "category": "娱乐", "app": "steam.exe", "title": "Steam", "start": 70, "end": 100},
            {"state": "away", "category": None, "app": "chrome.exe", "title": "x", "start": 100, "end": 200},
        ]
        out = usage.build_category_breakdown(segs)
        fun = out["娱乐"]
        self.assertEqual(fun["apps"][0]["name"], "chrome.exe")
        self.assertEqual(fun["apps"][0]["seconds"], 70)
        self.assertEqual(len(fun["titles"]), 3)
        self.assertEqual(out["学习"]["apps"], [])

    def test_ignore_apps_dropped_from_breakdown(self):
        segs = [
            {"state": "active", "category": "系统", "app": "explorer.exe", "title": "x", "start": 0, "end": 40},
            {"state": "active", "category": "工作", "app": "code.exe", "title": "a", "start": 40, "end": 80},
        ]
        out = usage.build_category_breakdown(segs, ignore_apps=["explorer.exe"])
        self.assertEqual(out["系统"]["apps"], [])
        self.assertEqual(out["工作"]["apps"][0]["name"], "code.exe")


class ClockPaintTests(unittest.TestCase):
    def test_split_never_skips_or_rewinds(self):
        prev = None
        for i in range(0, 8001):
            t = i / 1000.0
            if t < 3:
                a, _, _ = usage.paint_totals(0, 0, 0, 0.0, "active", t)
            else:
                a, _, _ = usage.paint_totals(3.0, 0, 0, 3.0, "active", t)
            shown = int(a)
            if prev is not None:
                self.assertGreaterEqual(shown, prev)
                self.assertLessEqual(shown - prev, 1, "jumped %s at t=%.3f" % (shown - prev, t))
            prev = shown
        self.assertEqual(int(usage.paint_totals(3.0, 0, 0, 3.0, "active", 8.0)[0]), 8)

    def test_old_reset_plus_live_can_skip_two(self):
        base = 100.0
        t0 = 0.0
        def old_paint(now):
            extra = int((now - t0) // 1)
            return int(base + extra)
        shown_at_3 = old_paint(3.0)
        after_stall_refresh = int(105.2)
        self.assertGreaterEqual(after_stall_refresh - shown_at_3, 2)

    def test_new_formula_matches_across_refresh(self):
        start = 1000.0
        closed = 50.0
        t1 = 1004.4
        a1, _, _ = usage.paint_totals(closed, 0, 0, start, "active", t1)
        t2 = 1004.4
        a2, _, _ = usage.paint_totals(closed, 0, 0, start, "active", t2)
        self.assertAlmostEqual(a1, a2)
        self.assertAlmostEqual(a1, 54.4, places=5)

    def test_step_sec_splits_two_second_gap(self):
        def step(cur, target):
            target = int(target)
            if cur is None:
                return target
            if target < cur - 2:
                return target
            if target > cur + 3:
                return target - 1
            if target > cur:
                return cur + 1
            return cur
        self.assertEqual(step(103, 105), 104)
        self.assertEqual(step(104, 105), 105)
        self.assertEqual(step(105, 105), 105)


class PetGeomTests(unittest.TestCase):
    def test_clamp_keeps_inside_work_area(self):
        import pet_geom
        work = (0, 0, 1707, 1067)
        x, y = pet_geom.clamp_pet_pos(2340, 1300, work)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + pet_geom.PET_W, 1707)
        self.assertLessEqual(y + pet_geom.PET_H, 1067)

    def test_default_pos_bottom_right(self):
        import pet_geom
        work = (0, 0, 1707, 1067)
        x, y = pet_geom.default_pet_pos_from_work(work)
        self.assertGreater(x, 1000)
        self.assertGreater(y, 600)
        self.assertTrue(pet_geom.rects_intersect(x, y, pet_geom.PET_W, pet_geom.PET_H, 0, 0, 1707, 1067))

    def test_sprites_are_png(self):
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet", "sprites")
        for name in ("front_187.png", "side_187.png", "back_187.png", "front_238.png", "front_306.png", "icon.png"):
            path = os.path.join(folder, name)
            self.assertTrue(os.path.isfile(path), path)
            with open(path, "rb") as f:
                self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_default_window_size(self):
        import pet_geom
        w, h = pet_geom.window_size(pet_geom.SIZE_H[pet_geom.DEFAULT_SIZE])
        self.assertEqual((w, h), (pet_geom.PET_W, pet_geom.PET_H))
        self.assertEqual(pet_geom.DEFAULT_SIZE, "小")
        self.assertGreater(h, 240)
        self.assertLess(h, 400)
        self.assertGreater(w, 240)
        metrics = pet_geom.bubble_metrics(pet_geom.SIZE_H["小"])
        self.assertGreaterEqual(w, metrics["band_w"])
        self.assertGreaterEqual(h - pet_geom.SIZE_H["小"], metrics["band_h"] - 8)


class PetEngineTests(unittest.TestCase):
    def test_dir_from_delta(self):
        import pet_engine
        self.assertEqual(pet_engine.dir_from_delta(-80, 10), ("left", 1))
        self.assertEqual(pet_engine.dir_from_delta(80, 10), ("right", -1))
        self.assertEqual(pet_engine.dir_from_delta(10, -80), ("up", 1))
        self.assertEqual(pet_engine.dir_from_delta(10, 80), ("down", 1))

    def test_wander_moves_then_rests(self):
        import pet_engine
        rng = pet_engine.random.Random(1)
        eng = pet_engine.PetEngine(80, 80, 218, 312, (0, 0, 1707, 1019), rng=rng)
        eng.set_mode("wander")
        saw_walk = False
        for _ in range(400):
            eng.tick()
            if eng.target is not None:
                saw_walk = True
            elif saw_walk:
                break
        self.assertTrue(saw_walk)
        self.assertIsNone(eng.target)
        self.assertGreater(eng.rest_until, 0)
        self.assertEqual(eng.dir, "down")

    def test_away_stops_walking(self):
        import pet_engine
        rng = pet_engine.random.Random(2)
        eng = pet_engine.PetEngine(80, 80, 218, 312, (0, 0, 1707, 1019), rng=rng)
        for _ in range(30):
            eng.tick()
        eng.away = True
        eng.tick()
        self.assertIsNone(eng.target)
        x0, y0 = eng.x, eng.y
        for _ in range(20):
            eng.tick()
        self.assertEqual((eng.x, eng.y), (x0, y0))

    def test_click_can_jump(self):
        import pet_engine
        class R:
            def random(self):
                return 0.1
            def choice(self, seq):
                return seq[0]
            def randint(self, a, b):
                return a
        eng = pet_engine.PetEngine(80, 80, 218, 312, (0, 0, 1707, 1019), rng=R())
        ev = eng.on_click()
        self.assertEqual(ev.get("jump"), 1.0)
        self.assertTrue(ev.get("say"))

    def test_idle_speaks_more_than_once(self):
        import pet_engine
        class R:
            n = 0
            def random(self):
                return 0.0
            def choice(self, seq):
                self.n += 1
                return seq[self.n % len(seq)]
            def randint(self, a, b):
                return a
        eng = pet_engine.PetEngine(80, 80, 174, 247, (0, 0, 1707, 1019), rng=R())
        eng.set_mode("still")
        said = 0
        for _ in range(500):
            ev = eng.tick()
            if ev.get("say"):
                said += 1
        self.assertGreaterEqual(said, 2)

    def test_custom_lines_are_sanitized_and_used(self):
        import pet_engine
        class R:
            def random(self):
                return 0.0
            def choice(self, seq):
                return seq[0]
            def randint(self, a, b):
                return a
        eng = pet_engine.PetEngine(80, 80, 174, 247, (0, 0, 1707, 1019), rng=R())
        lines = eng.set_custom_lines(["  你好   世界  ", "你好 世界", "", 3])
        self.assertEqual(lines, ("你好 世界",))
        eng.t = pet_engine.SPEAK_COOLDOWN_TICKS
        events = {}
        eng._maybe_speak(events, 1.0)
        self.assertEqual(events.get("say"), "你好 世界")
        self.assertFalse(events.get("inner"))

    def test_speech_levels_silent_and_chatty(self):
        import pet_engine
        class R:
            def random(self):
                return 0.025
            def choice(self, seq):
                return seq[0]
            def randint(self, a, b):
                return a
        quiet = pet_engine.PetEngine(0, 0, 174, 247, (0, 0, 800, 600), rng=R())
        quiet.t = pet_engine.SPEAK_COOLDOWN_TICKS
        quiet.set_speech_level("silent")
        events = {}
        quiet._maybe_speak(events, 1.0)
        self.assertNotIn("say", events)
        self.assertNotIn("say", quiet.on_click())
        quiet.on_drag_start()
        self.assertNotIn("say", quiet.on_drag_end(moved=True))
        chatty = pet_engine.PetEngine(0, 0, 174, 247, (0, 0, 800, 600), rng=R())
        chatty.t = pet_engine.SPEAK_COOLDOWN_TICKS
        chatty.set_custom_lines(["在这里"])
        chatty.set_speech_level("chatty")
        events = {}
        chatty._maybe_speak(events, 0.01)
        self.assertEqual(events.get("say"), "在这里")

    def test_custom_lines_have_hard_limits(self):
        import pet_engine
        lines = pet_engine.normalize_custom_lines([(str(i) + "-" + ("x" * 100)) for i in range(70)])
        self.assertEqual(len(lines), pet_engine.MAX_CUSTOM_LINES)
        self.assertTrue(all(len(x) <= pet_engine.MAX_CUSTOM_LINE_CHARS for x in lines))


class PetViewDrawTests(unittest.TestCase):
    def test_frame_has_transparent_corners(self):
        import pet_view
        import pet_engine
        import pet_geom
        w, h = pet_geom.window_size(187)
        eng = pet_engine.PetEngine(0, 0, w, h, (0, 0, 1200, 800))
        sprites = pet_view.load_sprites(187)
        im = pet_view.compose_frame(eng, sprites)
        self.assertEqual(im.mode, "RGBA")
        self.assertEqual(im.getpixel((1, 1))[3], 0)
        self.assertEqual(im.getpixel((w - 2, 2))[3], 0)

    def test_long_line_wraps_without_ellipsis(self):
        import pet_view
        import pet_engine
        import pet_geom
        line = pet_engine.LINES[5]
        w, h = pet_geom.window_size(187)
        eng = pet_engine.PetEngine(0, 0, w, h, (0, 0, 1200, 800))
        eng.say(line)
        sprites = pet_view.load_sprites(187)
        im = pet_view.compose_frame(eng, sprites)
        self.assertNotIn("…", eng.bubble_text)
        draw = pet_view.ImageDraw.Draw(im)
        font = pet_view._font(pet_geom.bubble_font_px(187))
        metrics = pet_geom.bubble_metrics(187)
        wrapped = pet_view._wrap_text(draw, eng.bubble_text, font, metrics["max_text_w"])
        self.assertEqual("".join(wrapped), eng.bubble_text)
        self.assertLessEqual(len(wrapped), 3)

    def test_timer_chip_drawn_above_head(self):
        import pet_view
        import pet_engine
        import pet_geom
        w, h = pet_geom.window_size(187)
        eng = pet_engine.PetEngine(0, 0, w, h, (0, 0, 1200, 800))
        eng.status_overlay = "专注 12:00"
        sprites = pet_view.load_sprites(187)
        im = pet_view.compose_frame(eng, sprites)
        self.assertGreater(im.getpixel((w // 2, 10))[3], 20)


class PetPackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ticko_pet_pack_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _png(self, size=(96, 128), color=(40, 120, 220, 255)):
        from PIL import Image
        buf = usage.io.BytesIO()
        Image.new("RGBA", size, color).save(buf, format="PNG")
        return buf.getvalue()

    def test_save_list_and_missing_directions_fallback(self):
        info, err = pet_packs.save_pack(self.tmp, "蓝色伙伴", {"front": self._png()})
        self.assertIsNone(err)
        self.assertTrue(info and info["id"].startswith("p"))
        self.assertEqual(info["kinds"], ["front"])
        items = pet_packs.list_packs(self.tmp)
        self.assertEqual(items[0]["id"], "default")
        self.assertEqual(items[1]["name"], "蓝色伙伴")
        import pet_view
        sprites = pet_view.load_sprites(187, pet_packs.safe_pack_dir(self.tmp, info["id"]))
        self.assertEqual(set(sprites), {"front", "side", "back"})
        self.assertTrue(all(24 <= im.height <= 187 for im in sprites.values()))

    def test_view_hot_switches_to_custom_pack(self):
        info, err = pet_packs.save_pack(self.tmp, "热切换", {"front": self._png()})
        self.assertIsNone(err)
        import pet_engine
        import pet_view
        eng = pet_engine.PetEngine(0, 0, 218, 312, (0, 0, 1200, 800))
        class Host:
            def ensure_engine(self):
                return eng
            def pet_sprite_dir(self, pack_id):
                return pet_packs.safe_pack_dir(self_root, pack_id)
        self_root = self.tmp
        view = pet_view.PetView(Host())
        view.apply_pet_settings({"pet_pack": info["id"]})
        self.assertEqual(eng.pet_pack_id, info["id"])
        self.assertEqual(view.sprites["front"].getpixel((0, 0)), (40, 120, 220, 255))

    def test_png_validation_and_safe_paths(self):
        size, err = pet_packs.validate_png(self._png())
        self.assertEqual(size, (96, 128))
        self.assertIsNone(err)
        self.assertIsNotNone(pet_packs.validate_png(b"bad")[1])
        self.assertIsNotNone(pet_packs.validate_png(self._png((8, 8)))[1])
        self.assertIsNone(pet_packs.safe_pack_dir(self.tmp, "../escape"))
        self.assertIsNone(pet_packs.safe_pack_file(self.tmp, "default", "secret.txt"))

    def test_delete_custom_but_never_default(self):
        info, err = pet_packs.save_pack(self.tmp, "可删除", {"front": self._png()})
        self.assertIsNone(err)
        self.assertFalse(pet_packs.delete_pack(self.tmp, "default"))
        self.assertTrue(pet_packs.delete_pack(self.tmp, info["id"]))
        self.assertEqual([x["id"] for x in pet_packs.list_packs(self.tmp)], ["default"])


class ThemePathTests(unittest.TestCase):
    def test_reject_traversal(self):
        import theme_util
        root = r"C:\themes"
        self.assertIsNone(theme_util.safe_theme_path(root, "../x"))
        self.assertIsNone(theme_util.safe_theme_path(root, "ok", "../secret.png"))
        self.assertIsNone(theme_util.safe_theme_path(root, "ok", "x.exe"))
        p = theme_util.safe_theme_path(root, "t1", "wall.gif")
        self.assertTrue(p.replace("/", "\\").endswith("\\t1\\wall.gif"))

    def test_app_icon_rejects_non_executable_name(self):
        self.assertIsNone(usage._app_icon_file("../not-an-app.exe"))
        self.assertIsNone(usage._app_icon_file("chrome.exe/anything"))


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00"
    b"\x00\x03\x01\x01\x00\x18\xdd\x8d\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
    b"\xff\xff\xff\x00\x00\x00!\xf9\x04"
    b"\x00\x00\x00\x00\x00,\x00\x00"
    b"\x00\x00\x01\x00\x01\x00\x00\x02"
    b"\x02D\x01\x00;"
)


class ThemeUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_themes = usage.THEMES_DIR
        usage.THEMES_DIR = self.tmp
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = usage.Storage(self.db_path)
        usage.Handler.store = self.store
        self.handler = usage.Handler.__new__(usage.Handler)
        self.handler.store = self.store
        self._sent = {}

        def _send(code, data):
            self._sent["code"] = code
            if isinstance(data, bytes):
                self._sent["data"] = json.loads(data.decode("utf-8"))
            else:
                self._sent["data"] = json.loads(data)

        self.handler._send = _send

    def tearDown(self):
        usage.THEMES_DIR = self._orig_themes
        usage.Handler.store = None
        try:
            self.store.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        for path in (self.db_path, self.db_path + "-wal", self.db_path + "-shm"):
            try:
                os.remove(path)
            except Exception:
                pass

    def _multipart(self, fields, files):
        boundary = "----testboundary"
        body = b""
        for name, val in fields.items():
            body += (
                "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                % (boundary, name, val)
            ).encode("utf-8")
        for name, spec in files.items():
            filename, content, ctype = spec
            body += (
                "--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                "Content-Type: %s\r\n\r\n" % (boundary, name, filename, ctype)
            ).encode("utf-8")
            body += content + b"\r\n"
        body += ("--%s--\r\n" % boundary).encode("utf-8")
        return "multipart/form-data; boundary=%s" % boundary, body

    def _upload(self, filename, content, ctype="image/png", display="测试壁纸"):
        ctype_hdr, body = self._multipart(
            {"name": display, "overlay": "0.25"},
            {"file": (filename, content, ctype)},
        )
        self.handler.headers = {"Content-Type": ctype_hdr}
        self._sent = {}
        self.handler._upload_theme(body)
        return self._sent

    def test_upload_png_lists_and_serves(self):
        sent = self._upload("wall.png", TINY_PNG)
        self.assertEqual(sent.get("code"), 200)
        data = sent["data"]
        self.assertTrue(data.get("ok"))
        tid = data.get("id")
        self.assertTrue(tid)
        wall_path = os.path.join(self.tmp, tid, "wall.png")
        self.assertTrue(os.path.isfile(wall_path))
        packs = usage.list_theme_packs()
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0]["id"], tid)
        settings = self.handler.api_settings()
        self.assertTrue(settings.get("background"))
        self.assertIn(tid, settings["background"])
        fpath = usage.theme_util.safe_theme_path(self.tmp, tid, "wall.png")
        self.assertTrue(os.path.isfile(fpath))
        self.handler.path = settings["background"]
        codes = []

        def _send_file(code, *_a, **_k):
            codes.append(code)

        orig = usage.Handler._file
        try:
            usage.Handler._file = lambda self, path, mime: codes.append(200)
            self.handler._theme_file(settings["background"])
        finally:
            usage.Handler._file = orig
        self.assertEqual(codes, [200])

    def test_upload_gif(self):
        sent = self._upload("anim.gif", TINY_GIF, ctype="image/gif")
        self.assertEqual(sent.get("code"), 200)
        tid = sent["data"].get("id")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, tid, "wall.gif")))

    def test_default_name_from_filename(self):
        sent = self._upload("sunset.png", TINY_PNG, display="")
        self.assertEqual(sent.get("code"), 200)
        tid = sent["data"].get("id")
        packs = {p["id"]: p for p in usage.list_theme_packs()}
        self.assertEqual(packs[tid]["name"], "sunset")

    def test_delete_theme(self):
        sent = self._upload("wall.png", TINY_PNG)
        tid = sent["data"].get("id")
        self.handler.headers = {"Content-Type": "application/json"}
        self._sent = {}
        self.handler._handle_themes_post(json.dumps({"action": "delete", "id": tid}).encode("utf-8"))
        self.assertEqual(self._sent.get("code"), 200)
        self.assertFalse(os.path.isdir(os.path.join(self.tmp, tid)))
        self.assertEqual(usage.list_theme_packs(), [])
        self.assertEqual(self.store.get_meta("theme_id") or "", "")

    def test_orphan_json_only_removed(self):
        orphan = os.path.join(self.tmp, "torphant123456")
        os.makedirs(orphan, exist_ok=True)
        with open(os.path.join(orphan, "theme.json"), "w", encoding="utf-8") as f:
            f.write('{"name":"坏主题","background":"wall.gif","overlay":0.5}')
        packs = usage.list_theme_packs()
        self.assertEqual(packs, [])
        self.assertFalse(os.path.isdir(orphan))


def _dashboard_inline_js():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    start = text.rfind("<script>")
    end = text.rfind("</script>")
    return text, text[start + 8:end] if start != -1 and end > start else ""


def _js_delims_balanced(src):
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = {")", "]", "}"}
    regex_prev = set("({[=,:;!&|?~+-*%<>\n\r")
    stack = []
    last = "\n"
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in "'\"":
            q = ch
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == q:
                    break
                i += 1
            i += 1
            last = "x"
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] not in "\n\r":
                i += 1
            last = "\n"
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            last = "x"
            continue
        if ch == "/" and last in regex_prev:
            i += 1
            in_class = False
            while i < n:
                c = src[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "[" and not in_class:
                    in_class = True
                elif c == "]" and in_class:
                    in_class = False
                elif c == "/" and not in_class:
                    i += 1
                    while i < n and src[i].isalpha():
                        i += 1
                    break
                i += 1
            last = "x"
            continue
        if ch in pairs:
            stack.append(pairs[ch])
            last = ch
        elif ch in closing:
            if not stack or stack[-1] != ch:
                return False, ch, i
            stack.pop()
            last = ch
        elif not ch.isspace():
            last = ch
        i += 1
    return (not stack), "".join(stack), len(src)


class DashboardJsTests(unittest.TestCase):
    def test_inline_script_parses(self):
        html, js = _dashboard_inline_js()
        self.assertIn("function dayBarTip", js)
        self.assertIn("function showPage", js)
        self.assertIn("function refresh", js)
        self.assertIn("function paintGoalCards", js)
        self.assertIn("function parseDurText", js)
        self.assertIn("function renderCatStrip", js)
        self.assertIn("function stepDurField", js)
        self.assertIn("dur-stepper", js)
        self.assertIn('id="goalPanel"', html)
        self.assertIn('id="catStrip"', html)
        self.assertIn('id="showPet"', html)
        self.assertIn("function paintPomodoro", js)
        self.assertIn("function pollPomo", js)
        self.assertIn('id="page-timer"', html)
        self.assertIn('id="pomoClock"', html)
        self.assertIn("试听当前铃声", html)
        self.assertIn("模拟专注结束", html)
        self.assertNotIn('id="up"', html)
        self.assertNotIn("wall-tools", html)
        self.assertIn("25 分钟 · 休息 5 分钟", html)
        self.assertIn('class="panel timer-hero"', html)
        self.assertIn('class="timer-subgrid"', html)
        self.assertIn("<summary>测试提醒</summary>", html)
        self.assertIn('id="pomoFocus"', html)
        self.assertIn("保存时长", html)
        self.assertIn("function fillPomoDur", js)
        self.assertIn("pomoDurDirty", js)
        self.assertIn("function applyAppearance", js)
        self.assertNotIn('id="wallPreview"', html)
        self.assertNotIn('id="packSelect"', html)
        self.assertIn('id="savePetSettings"', html)
        self.assertIn('id="petMode"', html)
        self.assertIn('id="petSize"', html)
        self.assertIn('id="petSpeech"', html)
        self.assertIn('id="petLines"', html)
        self.assertIn('id="petPackList"', html)
        self.assertIn('id="petPackUpload"', html)
        self.assertIn("function renderPetPacks", js)
        self.assertIn("function loadPetPacks", js)
        self.assertIn("function fillPetSettings", js)
        self.assertIn("pet_lines: lines", js)
        self.assertIn('id="appList"', html)
        self.assertIn("function appIcon", js)
        self.assertNotRegex(js, r"\}\s*\n  return \(seg\.category")
        ok, leftover, pos = _js_delims_balanced(js)
        self.assertTrue(ok, "dashboard.html script delimiters unbalanced near %s leftover=%r" % (pos, leftover))

    def test_pages_hidden_until_showPage(self):
        html, _js = _dashboard_inline_js()
        self.assertIn('class="page" id="page-overview"', html)
        self.assertIn("function showPage", _js)


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = usage.Storage(self.path)

    def tearDown(self):
        try:
            self.store.conn.close()
        except Exception:
            pass
        try:
            os.remove(self.path)
        except Exception:
            pass
        for extra in (self.path + "-wal", self.path + "-shm"):
            try:
                os.remove(extra)
            except Exception:
                pass

    def test_dashboard_payload_has_goals_and_ignore(self):
        usage.Handler.store = self.store
        usage.Handler.tracker = None
        handler = usage.Handler.__new__(usage.Handler)
        data = handler.api_dashboard()
        self.assertIn("today", data)
        self.assertIn("goals_progress", data)
        self.assertIsInstance(data["goals_progress"], list)
        settings = handler.api_settings()
        self.assertIn("ignore_apps", settings)
        self.assertIn("ticko.exe", settings["ignore_apps"])
        self.assertIn("daily_goals", settings)
        self.assertEqual(settings["pet_mode"], "wander")
        self.assertEqual(settings["pet_size"], "小")
        self.assertEqual(settings["pet_speech"], "normal")
        self.assertEqual(settings["pet_lines"], [])
        self.assertEqual(settings["pet_pack"], "default")
        usage.Handler.store = None

    def test_pet_settings_post_persists_validates_and_notifies(self):
        usage.Handler.store = self.store
        handler = usage.Handler.__new__(usage.Handler)
        handler.store = self.store
        handler.path = "/api/settings"
        payload = json.dumps({
            "pet_mode": "follow",
            "pet_size": "中",
            "pet_speech": "chatty",
            "pet_lines": ["  第一  句 ", "第一 句", "第二句"],
        }, ensure_ascii=False).encode("utf-8")
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = usage.io.BytesIO(payload)
        sent = {}
        handler._send = lambda code, data: sent.update(code=code, data=json.loads(data))
        calls = []
        usage.register_pet_hooks(None, None, lambda settings: calls.append(settings))
        try:
            handler.do_POST()
            self.assertEqual(sent["code"], 200)
            settings = sent["data"]["settings"]
            self.assertEqual(settings["pet_mode"], "follow")
            self.assertEqual(settings["pet_size"], "中")
            self.assertEqual(settings["pet_speech"], "chatty")
            self.assertEqual(settings["pet_lines"], ["第一 句", "第二句"])
            self.assertEqual(calls, [{k: settings[k] for k in ("pet_mode", "pet_size", "pet_speech", "pet_lines", "pet_pack")}])
        finally:
            usage.register_pet_hooks(None, None)
            usage.Handler.store = None

    def test_pomodoro_snapshot_shape(self):
        import pomodoro_util
        pomodoro_util.stop(now=0)
        snap = pomodoro_util.snapshot(now=1)
        self.assertIn("mode", snap)
        self.assertEqual(snap["mode"], "idle")
        self.assertIn("label", snap)
        self.assertIn("last_event_at", snap)


class PetOpenDashboardTests(unittest.TestCase):
    def test_menu_paths_open_expected_pages(self):
        import inspect
        import pet_view
        goals = inspect.getsource(pet_view.PetView._on_goals)
        timer = inspect.getsource(pet_view.PetView._on_pomo_settings)
        self.assertIn('open_dashboard_page("#settings")', goals)
        self.assertIn('open_dashboard_page("#timer")', timer)
        pause = inspect.getsource(pet_view.PetView._on_pomo_pause)
        stop = inspect.getsource(pet_view.PetView._on_pomo_stop)
        self.assertNotIn("evaluate_js", pause)
        self.assertNotIn("evaluate_js", stop)

    def test_open_dashboard_does_not_block_on_js(self):
        import main_app
        started = threading.Event()
        released = threading.Event()
        called = []

        class FakeWin:
            def show(self):
                pass

            def restore(self):
                pass

            def evaluate_js(self, script):
                called.append(script)
                started.set()
                released.wait(2)

        old = main_app._state.get("window")
        main_app._state["window"] = FakeWin()
        try:
            t0 = time.perf_counter()
            main_app.open_dashboard_page("#timer")
            self.assertLess(time.perf_counter() - t0, 0.4)
            self.assertTrue(started.wait(1.5), "evaluate_js was not scheduled")
            self.assertTrue(any("#timer" in s for s in called))
            self.assertTrue(any("showPage" in s for s in called))
        finally:
            released.set()
            main_app._state["window"] = old

    def test_bring_to_front_does_not_block_on_show(self):
        import main_app
        started = threading.Event()
        released = threading.Event()

        class FakeWin:
            def show(self):
                started.set()
                released.wait(2)

            def restore(self):
                pass

        old = main_app._state.get("window")
        main_app._state["window"] = FakeWin()
        try:
            t0 = time.perf_counter()
            main_app.bring_to_front()
            self.assertLess(time.perf_counter() - t0, 0.4)
            self.assertTrue(started.wait(1.5), "window.show was not scheduled")
        finally:
            released.set()
            main_app._state["window"] = old


class WindowSpaceTests(unittest.TestCase):
    def _monitors(self):
        a = window_space.Monitor(
            "A", window_space.Rect(0, 0, 1000, 800),
            window_space.Rect(0, 0, 1000, 760), is_primary=True)
        b = window_space.Monitor(
            "B", window_space.Rect(1000, 0, 1000, 800),
            window_space.Rect(1000, 0, 1000, 760), is_primary=False)
        return a, b

    def test_rect_contains_typical(self):
        outer = window_space.Rect(0, 0, 100, 100)
        inner = window_space.Rect(10, 10, 50, 50)
        self.assertTrue(window_space.rect_contains(outer, inner))

    def test_rect_contains_edge_touch(self):
        outer = window_space.Rect(0, 0, 100, 100)
        self.assertTrue(window_space.rect_contains(outer, outer))
        self.assertTrue(window_space.rect_contains(outer, window_space.Rect(0, 0, 40, 40)))

    def test_rect_contains_partial_outside(self):
        outer = window_space.Rect(0, 0, 100, 100)
        inner = window_space.Rect(50, 50, 80, 80)
        self.assertFalse(window_space.rect_contains(outer, inner))

    def test_rect_contains_none(self):
        outer = window_space.Rect(0, 0, 100, 100)
        self.assertFalse(window_space.rect_contains(None, outer))
        self.assertFalse(window_space.rect_contains(outer, None))

    def test_rect_intersects_overlap(self):
        self.assertTrue(window_space.rect_intersects(
            window_space.Rect(0, 0, 100, 100), window_space.Rect(50, 50, 100, 100)))

    def test_rect_intersects_edge_touch(self):
        a = window_space.Rect(0, 0, 100, 100)
        b = window_space.Rect(100, 0, 100, 100)
        self.assertFalse(window_space.rect_intersects(a, b))

    def test_rect_intersects_disjoint(self):
        self.assertFalse(window_space.rect_intersects(
            window_space.Rect(0, 0, 100, 100), window_space.Rect(500, 500, 100, 100)))

    def test_rect_intersects_none(self):
        a = window_space.Rect(0, 0, 100, 100)
        self.assertFalse(window_space.rect_intersects(None, a))
        self.assertFalse(window_space.rect_intersects(a, None))

    def test_monitor_for_rect_max_overlap(self):
        a, b = self._monitors()
        r = window_space.Rect(950, 100, 200, 200)
        self.assertIs(window_space.monitor_for_rect([a, b], r), b)

    def test_monitor_for_rect_no_overlap_returns_primary(self):
        a, b = self._monitors()
        r = window_space.Rect(5000, 5000, 100, 100)
        self.assertIs(window_space.monitor_for_rect([a, b], r), a)

    def test_monitor_for_rect_tie_prefers_primary(self):
        a, b = self._monitors()
        r = window_space.Rect(900, 100, 200, 200)
        self.assertIs(window_space.monitor_for_rect([a, b], r), a)

    def test_monitor_for_rect_empty_returns_none(self):
        self.assertIsNone(window_space.monitor_for_rect([], window_space.Rect(0, 0, 10, 10)))
        self.assertIsNone(window_space.monitor_for_rect(None, window_space.Rect(0, 0, 10, 10)))

    def test_monitor_for_rect_none_rect(self):
        a, b = self._monitors()
        self.assertIsNone(window_space.monitor_for_rect([a, b], None))

    def test_is_fullscreen_within_tolerance(self):
        m = window_space.Rect(0, 0, 1000, 800)
        self.assertTrue(window_space.is_fullscreen_rect(window_space.Rect(1, 1, 998, 798), m, tolerance=2))
        self.assertTrue(window_space.is_fullscreen_rect(window_space.Rect(0, 0, 1002, 802), m, tolerance=2))

    def test_is_fullscreen_outside_tolerance(self):
        m = window_space.Rect(0, 0, 1000, 800)
        self.assertFalse(window_space.is_fullscreen_rect(window_space.Rect(5, 5, 1000, 800), m, tolerance=2))
        self.assertFalse(window_space.is_fullscreen_rect(window_space.Rect(3, 3, 1000, 800), m, tolerance=0))

    def test_is_fullscreen_exact(self):
        m = window_space.Rect(0, 0, 1000, 800)
        self.assertTrue(window_space.is_fullscreen_rect(window_space.Rect(0, 0, 1000, 800), m))

    def test_is_fullscreen_none(self):
        r = window_space.Rect(0, 0, 10, 10)
        self.assertFalse(window_space.is_fullscreen_rect(None, r))
        self.assertFalse(window_space.is_fullscreen_rect(r, None))

    def test_valid_window_candidate_visible_large(self):
        w = window_space.WindowInfo("W1", window_space.Rect(0, 0, 200, 200), is_visible=True)
        self.assertTrue(window_space.valid_window_candidate(w))

    def test_valid_window_candidate_invisible(self):
        w = window_space.WindowInfo("W1", window_space.Rect(0, 0, 200, 200), is_visible=False)
        self.assertFalse(window_space.valid_window_candidate(w))

    def test_valid_window_candidate_small(self):
        w = window_space.WindowInfo("W1", window_space.Rect(0, 0, 50, 50), is_visible=True)
        self.assertFalse(window_space.valid_window_candidate(w))

    def test_valid_window_candidate_self(self):
        w = window_space.WindowInfo("PET", window_space.Rect(0, 0, 200, 200), is_visible=True)
        self.assertFalse(window_space.valid_window_candidate(w, pet_handle="PET"))

    def test_valid_window_candidate_none(self):
        self.assertFalse(window_space.valid_window_candidate(None))
        self.assertFalse(window_space.valid_window_candidate(None, pet_handle="PET"))

    def test_valid_window_candidate_malformed(self):
        class Bad:
            pass

        self.assertFalse(window_space.valid_window_candidate(Bad()))
        no_rect = window_space.WindowInfo("X", None, is_visible=True)
        self.assertFalse(window_space.valid_window_candidate(no_rect))

    def test_empty_inputs_do_not_raise(self):
        window_space.rect_contains(None, None)
        window_space.rect_intersects(None, None)
        window_space.monitor_for_rect([], None)
        window_space.is_fullscreen_rect(None, None)
        window_space.valid_window_candidate(None)
        self.assertIsNone(window_space.monitor_for_rect(None, window_space.Rect(0, 0, 1, 1)))

    def test_models_are_immutable(self):
        r = window_space.Rect(1, 2, 3, 4)
        self.assertEqual((r.x, r.y, r.width, r.height), (1, 2, 3, 4))
        self.assertEqual(r.right, 4)
        self.assertEqual(r.bottom, 6)
        with self.assertRaises(AttributeError):
            r.x = 9
        with self.assertRaises(AttributeError):
            r._x = 9
        m = window_space.Monitor("A", r, r, is_primary=True)
        with self.assertRaises(AttributeError):
            m.is_primary = False
        with self.assertRaises(AttributeError):
            m._is_primary = True
        space = window_space.WindowSpace([m], [], r)
        self.assertEqual(len(space.monitors), 1)
        self.assertEqual(len(space.windows), 0)
        self.assertIs(space.fallback_work_rect, r)
        with self.assertRaises(AttributeError):
            space.monitors = ()
        with self.assertRaises(AttributeError):
            space._monitors = ()

    def test_is_fullscreen_small_window_inside_is_false(self):
        m = window_space.Rect(0, 0, 1000, 800)
        # 屏幕内部的小窗口：四边都远未对齐显示器边缘，不能判为全屏
        w = window_space.Rect(100, 100, 200, 150)
        self.assertFalse(window_space.is_fullscreen_rect(w, m, tolerance=2))
        # 顶部居中的窄条窗口同样不是全屏
        w2 = window_space.Rect(300, 0, 400, 60)
        self.assertFalse(window_space.is_fullscreen_rect(w2, m, tolerance=2))

    def test_is_fullscreen_one_edge_outside_tolerance_is_false(self):
        m = window_space.Rect(0, 0, 1000, 800)
        # 仅底部超出容差
        self.assertFalse(window_space.is_fullscreen_rect(
            window_space.Rect(0, 0, 1000, 900), m, tolerance=2))
        # 仅左侧超出容差
        self.assertFalse(window_space.is_fullscreen_rect(
            window_space.Rect(-10, 0, 1010, 800), m, tolerance=2))
        # 仅顶部超出容差
        self.assertFalse(window_space.is_fullscreen_rect(
            window_space.Rect(0, -5, 1000, 805), m, tolerance=2))

    def test_is_fullscreen_exact_and_tolerance_cover_true(self):
        m = window_space.Rect(0, 0, 1000, 800)
        # 精确覆盖
        self.assertTrue(window_space.is_fullscreen_rect(
            window_space.Rect(0, 0, 1000, 800), m))
        # 容差内覆盖（每边均在 tolerance 内对齐）
        self.assertTrue(window_space.is_fullscreen_rect(
            window_space.Rect(1, 1, 998, 798), m, tolerance=2))
        # 容差内过扫描（略微超出每边，仍在 tolerance 内）
        self.assertTrue(window_space.is_fullscreen_rect(
            window_space.Rect(-1, -1, 1002, 802), m, tolerance=2))

    def test_monitor_for_rect_skips_malformed(self):
        a, b = self._monitors()

        class Bad:
            pass

        mixed = [None, Bad(), a, "not a monitor", b]
        # 最大交叠选择仍正确（忽略畸形项）
        r = window_space.Rect(950, 100, 200, 200)
        self.assertIs(window_space.monitor_for_rect(mixed, r), b)
        # 无交叠回退主屏仍正确
        r2 = window_space.Rect(5000, 5000, 100, 100)
        self.assertIs(window_space.monitor_for_rect(mixed, r2), a)

    def test_monitor_for_rect_all_malformed_returns_none(self):
        class Bad:
            pass

        mixed = [None, Bad(), "not a monitor"]
        self.assertIsNone(window_space.monitor_for_rect(
            mixed, window_space.Rect(0, 0, 10, 10)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
