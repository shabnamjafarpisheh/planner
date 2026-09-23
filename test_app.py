"""Tests for app.py. Run with:  python -m unittest discover tests
(No test framework to install; this uses the standard library.)
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402  (importing does not start the Streamlit interface)
from app import (Accounts, Store, ValidationError, classify, connect,  # noqa: E402
                 free_windows, parse_capture, parse_date, plan_day, plan_week)

ag = pv = app

TODAY = "2026-09-16"  # a Wednesday
CTX = {"today": TODAY, "now": None}


FAST = 1_000  # password hashing work factor for tests only; the app uses 600,000


def fresh(email="me@example.com"):
    conn = connect(":memory:")
    user = Accounts(conn, iterations=FAST).create(email, "correct horse 42", "Sam")
    return Store(conn, user["id"])


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.s = fresh()

    def test_defaults_and_validation(self):
        t = self.s.create_task(title="Write the brief")
        self.assertEqual(t["status"], "inbox")
        self.assertEqual(t["priority"], 3)  # normal, not high
        self.assertIsNone(t["due_date"])
        dated = self.s.create_task(title="Pay rent", due_date="2026-10-01")
        self.assertEqual(dated["status"], "planned")
        with self.assertRaises(ValidationError):
            self.s.create_task(title="")
        with self.assertRaises(ValidationError):
            self.s.create_task(title="Bad date", due_date="2026-02-30")
        with self.assertRaises(ValidationError):
            self.s.create_task(title="Bad priority", priority=9)

    def test_complete_reopen_and_dependency_warning(self):
        first = self.s.create_task(title="Draft copy")
        second = self.s.create_task(title="Publish page")
        self.s.add_dependency(second["id"], first["id"])
        done = self.s.complete_task(second["id"])
        self.assertEqual(done["status"], "completed")
        self.assertIn("Draft copy", done["warning"])
        self.assertEqual(self.s.reopen_task(second["id"])["status"], "planned")

    def test_dependency_cycles_are_refused(self):
        a = self.s.create_task(title="A")
        b = self.s.create_task(title="B")
        self.s.add_dependency(b["id"], a["id"])
        with self.assertRaises(ValidationError):
            self.s.add_dependency(a["id"], b["id"])
        with self.assertRaises(ValidationError):
            self.s.add_dependency(a["id"], a["id"])

    def test_bulk_move_is_all_or_nothing(self):
        a = self.s.create_task(title="A", scheduled_date=TODAY)
        b = self.s.create_task(title="B", scheduled_date=TODAY)
        with self.assertRaises(ValidationError):
            self.s.bulk_reschedule([a["id"], b["id"], 9999], "2026-09-17")
        self.assertEqual(self.s.get_task(a["id"])["scheduled_date"], TODAY)  # unchanged
        self.s.bulk_reschedule([a["id"], b["id"]], "2026-09-17")
        self.assertEqual(self.s.get_task(b["id"])["scheduled_date"], "2026-09-17")

    def test_split_chains_subtasks_and_delete_cascades(self):
        parent = self.s.create_task(title="Launch site", due_date="2026-09-30")
        out = self.s.split_task(parent["id"], [{"title": "Draft"}, {"title": "Review"}])
        self.assertEqual(len(out["subtasks"]), 2)
        self.assertEqual(out["subtasks"][1]["blocked_by"][0]["title"], "Draft")
        self.s.delete_task(parent["id"])
        self.assertEqual(self.s.list_tasks(), [])

    def test_overdue_and_unfinished(self):
        self.s.create_task(title="Invoice", due_date="2026-09-12")
        self.s.create_task(title="Review PR", scheduled_date="2026-09-15")
        self.s.create_task(title="Future", due_date="2026-12-01")
        self.assertEqual([t["title"] for t in self.s.overdue_tasks(TODAY)], ["Invoice"])
        self.assertEqual([t["title"] for t in self.s.unfinished_tasks(TODAY)], ["Review PR"])


class ProjectGoalTests(unittest.TestCase):
    def setUp(self):
        self.s = fresh()

    def test_duplicate_project_names_refused(self):
        self.s.create_project("Website")
        with self.assertRaises(ValidationError):
            self.s.create_project("website")

    def test_deleting_a_project_keeps_its_work(self):
        p = self.s.create_project("Website")
        t = self.s.create_task(title="Wireframes", project="Website")
        self.s.create_note(title="Ideas", content="hero", project="Website")
        self.s.delete_project(p["id"])
        self.assertIsNone(self.s.get_task(t["id"])["project_id"])
        self.assertEqual(len(self.s.list_notes()), 1)

    def test_goal_breakdown_is_atomic_and_tracks_progress(self):
        out = self.s.breakdown_goal("Learn Python", [
            {"name": "Basics", "tasks": [{"title": "Variables"}, {"title": "Loops"}]},
            {"name": "Project", "tasks": [{"title": "Build a CLI"}]},
        ], deadline="2026-12-01")
        goal = out["goal"]
        self.assertEqual(goal["task_count"], 3)
        self.assertEqual(goal["progress"], 0)
        first = self.s.list_tasks(goal_id=goal["id"])[0]
        self.s.complete_task(first["id"])
        self.assertEqual(self.s.get_goal(goal["id"])["progress"], 33)
        before = len(self.s.list_projects())
        with self.assertRaises(ValidationError):
            self.s.breakdown_goal("Broken", [{"name": ""}])
        self.assertEqual(len(self.s.list_projects()), before)  # nothing half-created


class SearchTests(unittest.TestCase):
    def test_search_includes_work_inside_a_matching_project(self):
        s = fresh()
        s.create_project("Marketing Website")
        s.create_task(title="Buy a lamp")  # unrelated
        s.create_task(title="Write homepage copy", project="Marketing Website")
        s.create_note(title="Hero ideas", content="simpler hero", project="Marketing Website")
        found = s.search("website")
        self.assertIn("Write homepage copy", [t["title"] for t in found["tasks"]])
        self.assertIn("Hero ideas", [n["title"] for n in found["notes"]])
        self.assertNotIn("Buy a lamp", [t["title"] for t in found["tasks"]])


class PlannerTests(unittest.TestCase):
    def task(self, **kw):
        base = {"id": kw.pop("id", 1), "title": "T", "status": "planned", "priority": 3,
                "due_date": None, "scheduled_date": None, "estimate_min": None, "blocked_by": []}
        base.update(kw)
        return base

    def test_classification(self):
        self.assertEqual(classify(self.task(due_date="2026-09-12"), TODAY)[0], "must")
        self.assertEqual(classify(self.task(due_date=TODAY), TODAY)[0], "must")
        self.assertEqual(classify(self.task(priority=1), TODAY)[0], "must")
        self.assertEqual(classify(self.task(scheduled_date=TODAY), TODAY)[0], "should")
        self.assertEqual(classify(self.task(), TODAY)[0], "nice")

    def test_free_windows_avoid_meetings(self):
        windows = free_windows(540, 1080, [{"start_time": "11:00", "end_time": "12:00"}])
        self.assertEqual(windows, [(540, 660), (720, 1080)])

    def test_plan_respects_capacity_and_meetings(self):
        tasks = [self.task(id=i, title=f"T{i}", estimate_min=60, due_date=TODAY) for i in range(1, 6)]
        plan = plan_day(tasks, TODAY, events=[{"title": "Standup", "start_time": "11:00", "end_time": "12:00"}],
                        available_min=120)
        self.assertLessEqual(plan["planned_min"], 120)
        self.assertTrue(plan["did_not_fit"])
        for block in plan["schedule"]:
            if block["type"] == "task":
                self.assertFalse("11:00" <= block["start"] < "12:00", "planned over a meeting")

    def test_no_break_after_a_short_stint(self):
        tasks = [self.task(id=1, title="Quick", estimate_min=15, due_date="2026-09-12"),
                 self.task(id=2, title="Long", estimate_min=90, due_date="2026-09-17")]
        plan = plan_day(tasks, TODAY, now="13:50", available_min=120)
        self.assertEqual(len([b for b in plan["schedule"] if b["type"] == "task"]), 2)
        self.assertFalse([b for b in plan["schedule"] if b["type"] == "break"])

    def test_break_after_long_continuous_work(self):
        tasks = [self.task(id=1, title="A", estimate_min=60, due_date=TODAY),
                 self.task(id=2, title="B", estimate_min=60, due_date=TODAY)]
        plan = plan_day(tasks, TODAY, workday_start="09:00", workday_end="18:00")
        self.assertTrue([b for b in plan["schedule"] if b["type"] == "break"])

    def test_blocked_tasks_are_left_out_with_a_warning(self):
        tasks = [self.task(id=1, title="Blocked", due_date=TODAY,
                           blocked_by=[{"id": 2, "title": "First", "status": "planned"}])]
        plan = plan_day(tasks, TODAY)
        self.assertTrue(plan["blocked"])
        self.assertTrue(any("waiting" in w for w in plan["warnings"]))

    def test_week_spreads_work_and_counts_only_time_left_today(self):
        tasks = [self.task(id=i, title=f"T{i}", estimate_min=60, due_date="2026-09-18")
                 for i in range(1, 7)]
        week = plan_week(tasks, TODAY, now="16:00")
        wed = next(d for d in week["days"] if d["date"] == TODAY)
        self.assertLessEqual(wed["capacity_min"], int(120 * 0.65) + 1)
        placed = sum(len(d["tasks"]) for d in week["days"])
        self.assertEqual(placed, 6)
        later = [d for d in week["days"] if TODAY < d["date"] <= "2026-09-18"]
        self.assertTrue(all(len(d["tasks"]) >= 2 for d in later), [len(d["tasks"]) for d in later])
        self.assertFalse([d for d in week["days"] if d["date"] > "2026-09-18" and d["tasks"]])


class CaptureTests(unittest.TestCase):
    def test_the_main_example_splits_correctly(self):
        text = ("I need to finish the website presentation by Monday, call Alex about the client "
                "meeting, buy a birthday gift for Sarah, and I had an idea for the landing page: "
                "maybe use a simpler hero section.")
        out = parse_capture(text, TODAY)
        titles = [t["title"] for t in out["tasks"]]
        self.assertEqual(len(titles), 3, titles)
        self.assertTrue(any("website presentation" in t.lower() for t in titles))
        self.assertTrue(any("alex" in t.lower() for t in titles))
        self.assertTrue(any("sarah" in t.lower() for t in titles))
        self.assertEqual(len(out["notes"]), 1)
        # Only the presentation has a deadline; nothing else is invented.
        dated = [t for t in out["tasks"] if t.get("due_date") or t.get("scheduled_date")]
        self.assertEqual(len(dated), 1)
        self.assertEqual(dated[0]["due_date"], "2026-09-21")  # the coming Monday
        self.assertIn("Alex", out["people"])

    def test_labelled_idea_becomes_a_titled_note(self):
        out = parse_capture("Email the landlord about the lease by Friday, and idea: a shared grocery list app",
                            TODAY)
        self.assertEqual(len(out["tasks"]), 1)
        self.assertEqual(out["tasks"][0]["due_date"], "2026-09-18")
        self.assertEqual(out["notes"][0]["title"], "Idea: a shared grocery list app")

    def test_date_phrases(self):
        self.assertEqual(parse_date("call her tomorrow", TODAY)[0], "2026-09-17")
        self.assertEqual(parse_date("due friday", TODAY)[:1] + (parse_date("due friday", TODAY)[2],),
                         ("2026-09-18", "due"))
        self.assertEqual(parse_date("in 3 days", TODAY)[0], "2026-09-19")
        self.assertEqual(parse_date("on october 2", TODAY)[0], "2026-10-02")
        self.assertEqual(parse_date("january 5", TODAY)[0], "2027-01-05")  # rolls to next year
        self.assertIsNone(parse_date("at some point soon", TODAY))


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.s = fresh()

    def test_destructive_actions_wait_for_confirmation(self):
        t = self.s.create_task(title="Important")
        result = ag.run_tool(self.s, "delete_task", {"id": t["id"]}, CTX)
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("Important", result["summary"])
        self.assertTrue(self.s.get_task(t["id"]))  # still there
        ag.resolve_pending(self.s, result["pending_action_id"], "confirm", CTX)
        self.assertEqual(self.s.list_tasks(), [])
        with self.assertRaises(ValidationError):  # can't decide twice
            ag.resolve_pending(self.s, result["pending_action_id"], "reject", CTX)

    def test_small_moves_do_not_need_confirmation(self):
        a = self.s.create_task(title="A", scheduled_date="2026-09-15")
        b = self.s.create_task(title="B", scheduled_date="2026-09-15")
        out = ag.run_tool(self.s, "bulk_reschedule", {"ids": [a["id"], b["id"]], "date": TODAY}, CTX)
        self.assertEqual(out["moved"], 2)
        c = self.s.create_task(title="C", scheduled_date="2026-09-15")
        out3 = ag.run_tool(self.s, "bulk_reschedule",
                           {"ids": [a["id"], b["id"], c["id"]], "date": TODAY}, CTX)
        self.assertTrue(out3["needs_confirmation"])

    def test_tool_loop_runs_tools_then_answers(self):
        calls = []

        def fake_model(body):
            calls.append(body)
            if len(calls) == 1:
                return {"stop_reason": "tool_use", "content": [
                    {"type": "tool_use", "id": "t1", "name": "create_task",
                     "input": {"title": "Call John", "scheduled_date": "2026-09-17"}}]}
            return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Added it."}]}

        out = ag.chat(self.s, "remind me to call John tomorrow", CTX, call_model=fake_model)
        self.assertEqual(out["mode"], "ai")
        self.assertEqual(out["reply"], "Added it.")
        self.assertIn('Added task "Call John"', out["actions"])
        self.assertEqual(self.s.list_tasks()[0]["title"], "Call John")
        self.assertTrue(calls[0]["tools"], "tools were offered to the model")

    def test_tool_errors_go_back_to_the_model(self):
        seen = []

        def fake_model(body):
            last = body["messages"][-1]
            if isinstance(last["content"], list) and last["content"][0].get("is_error"):
                seen.append(last["content"][0]["content"])
                return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Sorry, fixed."}]}
            return {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "get_task", "input": {"id": 999}}]}

        out = ag.chat(self.s, "show task 999", CTX, call_model=fake_model)
        self.assertEqual(out["reply"], "Sorry, fixed.")
        self.assertTrue(seen and "999" in seen[0])

    def test_fallback_when_the_ai_is_unavailable(self):
        self.s.create_task(title="Send invoice", due_date="2026-09-10")

        def dead(body):
            raise pv.AIUnavailable("free-tier limit reached")

        out = ag.chat(self.s, "what am I falling behind on?", CTX, call_model=dead)
        self.assertEqual(out["mode"], "basic")
        self.assertIn("Send invoice", out["reply"])
        self.assertIn("AI unavailable", out["notice"])

    def test_basic_mode_handles_common_requests(self):
        self.s.create_task(title="Fix the boiler", due_date=TODAY, estimate_min=30)
        plan = ag.chat(self.s, "plan my day", CTX)
        self.assertEqual(plan["mode"], "basic")
        self.assertIn("Fix the boiler", plan["reply"])
        captured = ag.chat(self.s, "buy milk tomorrow", CTX)
        self.assertTrue(any("Added task" in a for a in captured["actions"]))


class WeekPlanTests(unittest.TestCase):
    def test_never_plans_onto_days_already_gone(self):
        s = fresh()
        s.create_task(title="Overdue invoice", due_date="2026-09-12", estimate_min=15)
        s.create_task(title="Deck", due_date="2026-09-18", estimate_min=60)
        plan = ag.week_plan(s, "2026-09-14", now="10:00", today=TODAY)  # Monday's week, but it's Wednesday
        self.assertTrue(all(d["date"] >= TODAY for d in plan["days"]))
        self.assertTrue(all(c["to"] >= TODAY for c in plan["changes"]))
        self.assertIn("Overdue invoice", [c["title"] for c in plan["changes"]])

    def test_a_past_week_has_nothing_to_plan(self):
        s = fresh()
        s.create_task(title="Deck", due_date="2026-09-18")
        plan = ag.week_plan(s, "2026-09-01", today=TODAY)
        self.assertEqual(plan["changes"], [])
        self.assertIn("over", plan["assumptions"][0])

    def test_a_future_week_starts_on_its_monday(self):
        s = fresh()
        s.create_task(title="Later", due_date="2026-09-25")
        plan = ag.week_plan(s, "2026-09-21", today=TODAY)
        self.assertEqual(plan["days"][0]["date"], "2026-09-21")


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.s = fresh()

    def test_defaults_to_basic_mode(self):
        self.assertEqual(pv.resolve_config(self.s, env={})["provider"], "none")

    def test_saving_a_free_provider_turns_the_ai_on(self):
        pv.save_config(self.s, "gemini", api_key="AIza-test")
        cfg = pv.resolve_config(self.s, env={})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["model"], "gemini-2.5-flash")

    def test_provider_needing_a_key_explains_itself(self):
        pv.save_config(self.s, "groq")
        cfg = pv.resolve_config(self.s, env={})
        self.assertFalse(cfg["enabled"])
        self.assertIn("API key", cfg["problem"])

    def test_ollama_needs_no_key(self):
        pv.save_config(self.s, "ollama")
        self.assertTrue(pv.resolve_config(self.s, env={})["enabled"])

    def test_environment_wins_and_legacy_key_works(self):
        pv.save_config(self.s, "gemini", api_key="saved")
        cfg = pv.resolve_config(self.s, env={"AI_PROVIDER": "groq", "AI_API_KEY": "k"})
        self.assertEqual(cfg["provider"], "groq")
        self.assertEqual(cfg["source"], "env")
        self.assertEqual(pv.resolve_config(self.s, env={"ANTHROPIC_API_KEY": "sk"})["provider"], "anthropic")

    def test_changing_the_address_drops_the_saved_key(self):
        pv.save_config(self.s, "openai_compatible", api_key="k1", base_url="https://a.example", model="m")
        pv.save_config(self.s, "openai_compatible", model="m2", base_url="https://a.example")
        self.assertEqual(pv.resolve_config(self.s, env={})["api_key"], "k1")
        pv.save_config(self.s, "openai_compatible", model="m2", base_url="https://elsewhere.example")
        self.assertEqual(pv.resolve_config(self.s, env={})["api_key"], "")

    def test_bad_input_refused(self):
        with self.assertRaises(ValidationError):
            pv.save_config(self.s, "nope")
        with self.assertRaises(ValidationError):
            pv.save_config(self.s, "openai_compatible", base_url="javascript:alert(1)")

    def test_openai_round_trip(self):
        req = pv.to_openai_request({
            "system": "be brief", "max_tokens": 100,
            "tools": [{"name": "create_task", "description": "d",
                       "input_schema": {"type": "object", "properties": {}}}],
            "messages": [
                {"role": "user", "content": "add a task"},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "sure"},
                    {"type": "tool_use", "id": "c1", "name": "create_task", "input": {"title": "x"}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "c1", "content": '{"id":1}'}]},
            ]}, "some-model")
        self.assertEqual(req["messages"][0]["role"], "system")
        self.assertEqual(req["tools"][0]["function"]["name"], "create_task")
        self.assertEqual(json.loads(req["messages"][2]["tool_calls"][0]["function"]["arguments"]),
                         {"title": "x"})
        self.assertEqual(req["messages"][3]["role"], "tool")

    def test_openai_replies_convert_back(self):
        out = pv.from_openai_response({"choices": [{"message": {
            "content": "", "tool_calls": [{"id": "a", "function": {"name": "get_today", "arguments": "{}"}}]}}]})
        self.assertEqual(out["stop_reason"], "tool_use")
        plain = pv.from_openai_response({"choices": [{"message": {"content": "<think>hmm</think>Here."}}]})
        self.assertEqual(plain["content"][0]["text"], "Here.")
        broken = pv.from_openai_response({"choices": [{"message": {"tool_calls": [
            {"id": "a", "function": {"name": "create_task", "arguments": "{oops"}}]}}]})
        self.assertIn("_invalid_arguments", broken["content"][0]["input"])


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.acc = Accounts(self.conn, iterations=FAST)

    def test_create_and_sign_in(self):
        user = self.acc.create("Sam@Example.com", "correct horse 42", "Sam")
        self.assertEqual(user["email"], "sam@example.com")  # stored lowercase
        self.assertEqual(self.acc.authenticate("sam@example.com", "correct horse 42")["id"], user["id"])
        self.assertEqual(self.acc.authenticate("  SAM@example.com ", "correct horse 42")["id"], user["id"])

    def test_passwords_are_not_stored_in_plain_text(self):
        self.acc.create("a@example.com", "correct horse 42")
        row = self.conn.execute("SELECT password_hash, salt FROM users").fetchone()
        self.assertNotIn("correct horse", row["password_hash"])
        self.assertEqual(len(row["salt"]), 32)

    def test_same_password_gives_different_hashes(self):
        self.acc.create("a@example.com", "correct horse 42")
        self.acc.create("b@example.com", "correct horse 42")
        hashes = [r[0] for r in self.conn.execute("SELECT password_hash FROM users")]
        self.assertNotEqual(hashes[0], hashes[1])

    def test_sign_up_rules(self):
        with self.assertRaises(ValidationError):
            self.acc.create("not-an-email", "correct horse 42")
        with self.assertRaises(ValidationError):
            self.acc.create("a@example.com", "short")
        with self.assertRaises(ValidationError):
            self.acc.create("a@example.com", "aaaaaaaaaa")
        self.acc.create("a@example.com", "correct horse 42")
        with self.assertRaises(ValidationError):
            self.acc.create("A@example.com", "another pass 99")  # same email, different case

    def test_wrong_password_and_unknown_email_look_the_same(self):
        self.acc.create("a@example.com", "correct horse 42")
        with self.assertRaises(ValidationError) as wrong:
            self.acc.authenticate("a@example.com", "nope nope 1")
        with self.assertRaises(ValidationError) as unknown:
            self.acc.authenticate("ghost@example.com", "nope nope 1")
        self.assertEqual(str(wrong.exception), str(unknown.exception))

    def test_lockout_after_repeated_failures(self):
        self.acc.create("a@example.com", "correct horse 42")
        for _ in range(5):
            with self.assertRaises(ValidationError):
                self.acc.authenticate("a@example.com", "wrong password")
        with self.assertRaises(ValidationError) as locked:
            self.acc.authenticate("a@example.com", "correct horse 42")  # even the right one waits
        self.assertIn("Too many attempts", str(locked.exception))

    def test_change_password_and_delete_account(self):
        u = self.acc.create("a@example.com", "correct horse 42")
        with self.assertRaises(ValidationError):
            self.acc.change_password(u["id"], "wrong", "new password 77")
        self.acc.change_password(u["id"], "correct horse 42", "new password 77")
        self.acc.authenticate("a@example.com", "new password 77")
        s = Store(self.conn, u["id"])
        s.create_task(title="Mine")
        with self.assertRaises(ValidationError):
            self.acc.delete(u["id"], "wrong")
        self.acc.delete(u["id"], "new password 77")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_keep_me_signed_in(self):
        u = self.acc.create("a@example.com", "correct horse 42")
        token = self.acc.start_session(u["id"])
        self.assertEqual(self.acc.user_from_session(token)["id"], u["id"])
        stored = self.conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
        self.assertNotEqual(stored, token)  # only a hash is kept
        self.assertIsNone(self.acc.user_from_session("made-up-token"))
        self.acc.end_session(token)
        self.assertIsNone(self.acc.user_from_session(token))

    def test_sessions_expire_and_password_change_signs_out_everywhere(self):
        u = self.acc.create("a@example.com", "correct horse 42")
        old = self.acc.start_session(u["id"], days=-1)
        self.assertIsNone(self.acc.user_from_session(old))
        live = self.acc.start_session(u["id"])
        self.acc.change_password(u["id"], "correct horse 42", "new password 77")
        self.assertIsNone(self.acc.user_from_session(live))

    def test_signed_out_store_is_refused(self):
        with self.assertRaises(ValidationError):
            Store(self.conn, None)


class IsolationTests(unittest.TestCase):
    """One person can never read or change another person's things."""

    def setUp(self):
        self.conn = connect(":memory:")
        acc = Accounts(self.conn, iterations=FAST)
        self.a = Store(self.conn, acc.create("a@example.com", "correct horse 42")["id"])
        self.b = Store(self.conn, acc.create("b@example.com", "correct horse 42")["id"])
        self.task = self.a.create_task(title="A's secret task", due_date="2026-09-10")
        self.note = self.a.create_note(title="A's diary", content="private")
        self.project = self.a.create_project("A's project")
        self.goal = self.a.create_goal("A's goal")

    def test_lists_and_search_only_show_your_own(self):
        self.assertEqual(self.b.list_tasks(), [])
        self.assertEqual(self.b.list_notes(), [])
        self.assertEqual(self.b.list_projects(), [])
        self.assertEqual(self.b.list_goals(), [])
        self.assertEqual(self.b.overdue_tasks(TODAY), [])
        found = self.b.search("secret")
        self.assertEqual(found["tasks"] + found["notes"] + found["projects"], [])
        self.assertEqual(self.b.get_today(TODAY)["overdue"], [])

    def test_guessing_an_id_does_not_work(self):
        for fn in (lambda: self.b.get_task(self.task["id"]),
                   lambda: self.b.update_task(self.task["id"], title="hacked"),
                   lambda: self.b.complete_task(self.task["id"]),
                   lambda: self.b.delete_task(self.task["id"]),
                   lambda: self.b.bulk_reschedule([self.task["id"]], TODAY),
                   lambda: self.b.get_note(self.note["id"]),
                   lambda: self.b.update_note(self.note["id"], content="hacked"),
                   lambda: self.b.delete_note(self.note["id"]),
                   lambda: self.b.get_project(self.project["id"]),
                   lambda: self.b.delete_project(self.project["id"]),
                   lambda: self.b.get_goal(self.goal["id"])):
            with self.assertRaises(ValidationError):
                fn()
        self.assertEqual(self.a.get_task(self.task["id"])["title"], "A's secret task")
        self.assertEqual(self.a.get_note(self.note["id"])["content"], "private")

    def test_cannot_attach_your_task_to_someone_elses_project(self):
        with self.assertRaises(ValidationError):
            self.b.create_task(title="Sneaky", project_id=self.project["id"])
        mine = self.b.create_task(title="Mine")
        with self.assertRaises(ValidationError):
            self.b.update_task(mine["id"], project_id=self.project["id"])
        with self.assertRaises(ValidationError):
            self.b.add_dependency(mine["id"], self.task["id"])

    def test_same_project_name_is_fine_for_different_people(self):
        self.b.create_project("A's project")
        self.assertEqual(len(self.b.list_projects()), 1)

    def test_the_agent_is_limited_to_the_signed_in_person(self):
        out = ag.run_tool(self.b, "search_context", {"query": "secret"}, CTX)
        self.assertEqual(out["tasks"], [])
        with self.assertRaises(ValidationError):
            ag.run_tool_unchecked(self.b, "delete_task", {"id": self.task["id"]}, CTX)
        parked = ag.run_tool(self.a, "delete_task", {"id": self.task["id"]}, CTX)
        with self.assertRaises(ValidationError):  # B can't confirm A's pending action
            ag.resolve_pending(self.b, parked["pending_action_id"], "confirm", CTX)
        self.assertTrue(self.a.get_task(self.task["id"]))

    def test_settings_and_ai_keys_are_per_person(self):
        pv.save_config(self.a, "gemini", api_key="a-secret-key")
        self.assertEqual(pv.resolve_config(self.b, env={})["provider"], "none")
        self.assertEqual(pv.resolve_config(self.b, env={})["api_key"], "")

    def test_chat_history_is_per_person(self):
        self.a.add_message("user", "private thought")
        self.assertEqual(self.b.recent_messages(), [])


class SharingTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        acc = Accounts(self.conn, iterations=FAST)
        self.a = Store(self.conn, acc.create("a@example.com", "correct horse 42", "Ann")["id"])
        self.b = Store(self.conn, acc.create("b@example.com", "correct horse 42", "Ben")["id"])
        self.c = Store(self.conn, acc.create("c@example.com", "correct horse 42", "Cal")["id"])
        self.task = self.a.create_task(title="Book the venue", due_date="2026-09-18")

    def test_sharing_shows_the_task_to_the_other_person_only(self):
        self.a.share_task(self.task["id"], "b@example.com")
        self.assertEqual([t["title"] for t in self.b.list_tasks()], ["Book the venue"])
        self.assertEqual(self.b.shared_with_me()[0]["owner_name"], "Ann")
        self.assertEqual(self.a.shared_by_me()[0]["id"], self.task["id"])
        self.assertEqual(self.c.list_tasks(), [])                      # nobody else
        with self.assertRaises(ValidationError):
            self.c.get_task(self.task["id"])

    def test_either_person_can_finish_a_shared_task(self):
        self.a.share_task(self.task["id"], "b@example.com")
        self.b.complete_task(self.task["id"])
        self.assertEqual(self.a.get_task(self.task["id"])["status"], "completed")
        kinds = [n["kind"] for n in self.a.list_notifications()]
        self.assertIn("completed", kinds)                               # the owner hears about it
        self.assertNotIn("completed", [n["kind"] for n in self.b.list_notifications()])  # not told about own doing

    def test_a_viewer_can_look_but_not_change(self):
        self.a.share_task(self.task["id"], "b@example.com", role="viewer")
        self.assertFalse(self.b.get_task(self.task["id"])["can_edit"])
        for fn in (lambda: self.b.update_task(self.task["id"], title="hijacked"),
                   lambda: self.b.complete_task(self.task["id"]),
                   lambda: self.b.bulk_reschedule([self.task["id"]], TODAY)):
            with self.assertRaises(ValidationError):
                fn()
        self.assertEqual(self.a.get_task(self.task["id"])["title"], "Book the venue")

    def test_only_the_owner_deletes_or_shares(self):
        self.a.share_task(self.task["id"], "b@example.com")
        with self.assertRaises(ValidationError):
            self.b.delete_task(self.task["id"])
        with self.assertRaises(ValidationError):
            self.b.share_task(self.task["id"], "c@example.com")
        self.b.unshare_task(self.task["id"], self.b.uid)                # but can leave
        self.assertEqual(self.b.list_tasks(), [])
        self.assertTrue(self.a.get_task(self.task["id"]))

    def test_sharing_refuses_yourself_and_strangers(self):
        with self.assertRaises(ValidationError):
            self.a.share_task(self.task["id"], "a@example.com")
        with self.assertRaises(ValidationError):
            self.a.share_task(self.task["id"], "nobody@example.com")
        with self.assertRaises(ValidationError):
            self.a.share_task(self.task["id"], "b@example.com", role="owner")

    def test_sharing_does_not_leak_anything_else(self):
        self.a.create_task(title="A private thing")
        self.a.create_note(title="A private note", content="hush")
        self.a.share_task(self.task["id"], "b@example.com")
        self.assertEqual([t["title"] for t in self.b.list_tasks()], ["Book the venue"])
        self.assertEqual(self.b.list_notes(), [])
        found = self.b.search("private")
        self.assertEqual(found["tasks"] + found["notes"], [])

    def test_a_nudge_reaches_the_other_person(self):
        self.a.share_task(self.task["id"], "b@example.com")
        self.b.nudge(self.task["id"])
        self.assertEqual([n["kind"] for n in self.a.list_notifications()][0], "nudge")
        self.assertEqual(self.a.list_notifications()[0]["from_name"], "Ben")
        own = self.a.create_task(title="Just mine")
        with self.assertRaises(ValidationError):
            self.a.nudge(own["id"])

    def test_updates_are_counted_delivered_once_and_can_be_read(self):
        self.a.share_task(self.task["id"], "b@example.com")
        self.assertEqual(self.b.unread_count(), 1)
        first = self.b.undelivered_notifications()
        self.assertEqual(len(first), 1)
        self.b.mark_delivered([n["id"] for n in first])
        self.assertEqual(self.b.undelivered_notifications(), [])        # never shown twice
        self.assertEqual(self.b.unread_count(), 1)                      # still unread in the app
        self.b.mark_notifications_read()
        self.assertEqual(self.b.unread_count(), 0)

    def test_shared_tasks_join_the_day_plan(self):
        self.a.share_task(self.task["id"], "b@example.com")
        titles = [blk["title"] for blk in ag.day_plan(self.b, TODAY)["schedule"] if blk["type"] == "task"]
        self.assertIn("Book the venue", titles)


class StreakTests(unittest.TestCase):
    def test_counts_consecutive_days_ending_today_or_yesterday(self):
        s = fresh()
        for day in ("2026-09-14", "2026-09-15", "2026-09-16"):
            t = s.create_task(title=f"Done {day}")
            s.conn.execute("UPDATE tasks SET status='completed', completed_at=? WHERE id=?", (day + "T10:00:00", t["id"]))
        s.conn.commit()
        self.assertEqual(s.streak("2026-09-16"), 3)
        self.assertEqual(s.streak("2026-09-17"), 3)  # nothing yet today still keeps it
        self.assertEqual(s.streak("2026-09-19"), 0)


class LegacyMigrationTests(unittest.TestCase):
    def test_first_account_takes_over_data_from_the_single_user_version(self):
        import sqlite3
        import tempfile, os
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        old = sqlite3.connect(path)
        old.executescript("""
          CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
          CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
            goal_id INTEGER, due_date TEXT, status TEXT NOT NULL DEFAULT 'active', created_at TEXT);
          CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'inbox', priority INTEGER NOT NULL DEFAULT 3, due_date TEXT,
            scheduled_date TEXT, estimate_min INTEGER, project_id INTEGER, goal_id INTEGER, parent_id INTEGER,
            tags TEXT NOT NULL DEFAULT '', created_at TEXT, completed_at TEXT);
          CREATE TABLE notes (id INTEGER PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
            project_id INTEGER, goal_id INTEGER, tags TEXT NOT NULL DEFAULT '', created_at TEXT, updated_at TEXT);
          INSERT INTO settings VALUES ('workday_start', '08:00');
          INSERT INTO projects (id, name) VALUES (1, 'Website');
          INSERT INTO tasks (id, title, project_id, created_at) VALUES (1, 'Old task', 1, '2026-09-01');
          INSERT INTO notes (id, title, content, created_at, updated_at) VALUES (1, 'Old note', 'hi', '2026-09-01', '2026-09-01');
        """)
        old.commit()
        old.close()
        conn = connect(path)
        acc = Accounts(conn, iterations=FAST)
        first = Store(conn, acc.create("first@example.com", "correct horse 42")["id"])
        self.assertEqual([t["title"] for t in first.list_tasks()], ["Old task"])
        self.assertEqual(first.list_tasks()[0]["project_name"], "Website")
        self.assertEqual(first.list_notes()[0]["title"], "Old note")
        self.assertEqual(first.get_settings()["workday_start"], "08:00")
        second = Store(conn, acc.create("second@example.com", "correct horse 42")["id"])
        self.assertEqual(second.list_tasks(), [])  # only the first account takes it


class JalaliTests(unittest.TestCase):
    def test_known_dates(self):
        from app import iso_to_jalali, jalali_to_iso, jalali_month_length
        self.assertEqual(jalali_to_iso(1405, 1, 1), "2026-03-21")      # Nowruz 1405
        self.assertEqual(iso_to_jalali("2026-09-22"), (1405, 6, 31))
        self.assertEqual(iso_to_jalali("2025-03-20"), (1403, 12, 30))  # 1403 is a leap year
        self.assertEqual(jalali_month_length(1403, 12), 30)
        self.assertEqual(jalali_month_length(1404, 12), 29)
        with self.assertRaises(ValueError):
            jalali_to_iso(1404, 12, 30)

    def test_round_trip_over_many_years(self):
        from datetime import date, timedelta
        from app import iso_to_jalali, jalali_to_iso
        d = date(1990, 1, 1)
        while d < date(2060, 1, 1):
            self.assertEqual(jalali_to_iso(*iso_to_jalali(d.isoformat())), d.isoformat())
            d += timedelta(days=11)

    def test_formatting(self):
        from app import format_date, fa_digits
        self.assertEqual(format_date("2026-09-22", "fa", "jalali", with_year=True), "۳۱ شهریور ۱۴۰۵")
        self.assertEqual(format_date("2026-09-22", "en", "jalali"), "31 Shahrivar")
        self.assertEqual(format_date("2026-09-22", "fa", "gregorian"), "۲۲ سپتامبر")
        self.assertEqual(format_date("2026-09-22", "en", "gregorian", with_weekday=True), "Tuesday, September 22")
        self.assertEqual(fa_digits("09:30"), "۰۹:۳۰")


class PersianCaptureTests(unittest.TestCase):
    T = "2026-09-22"  # Tuesday

    def test_mixed_sentence(self):
        out = parse_capture("باید ارائهٔ سایت را تا دوشنبه تمام کنم، فردا به علی زنگ بزنم، "
                            "برای سارا هدیهٔ تولد بخرم و ایده: یک صفحهٔ اول ساده‌تر", self.T)
        titles = [t["title"] for t in out["tasks"]]
        self.assertEqual(titles, ["ارائهٔ سایت را تمام کنم", "به علی زنگ بزنم", "برای سارا هدیهٔ تولد بخرم"])
        self.assertEqual(out["tasks"][0]["due_date"], "2026-09-28")          # "by Monday" is a deadline
        self.assertEqual(out["tasks"][1]["scheduled_date"], "2026-09-23")    # "tomorrow" is a plan
        self.assertNotIn("due_date", out["tasks"][2])                        # no date given, none invented
        self.assertEqual(out["notes"][0]["title"], "ایده: یک صفحهٔ اول ساده‌تر")

    def test_and_inside_one_task_is_not_split(self):
        out = parse_capture("کتاب و دفتر بخرم", self.T)
        self.assertEqual([t["title"] for t in out["tasks"]], ["کتاب و دفتر بخرم"])

    def test_dates(self):
        from app import parse_date_fa
        self.assertEqual(parse_date_fa("پس‌فردا", self.T)[0], "2026-09-24")
        self.assertEqual(parse_date_fa("۳ روز دیگر", self.T)[0], "2026-09-25")
        self.assertEqual(parse_date_fa("تا ۱۵ مهر", self.T)[:1] + (parse_date_fa("تا ۱۵ مهر", self.T)[2],),
                         ("2026-10-07", "due"))
        self.assertEqual(parse_date_fa("پنج‌شنبه", self.T)[0], "2026-09-24")
        self.assertEqual(parse_date_fa("شنبه", self.T)[0], "2026-09-26")
        self.assertEqual(parse_date_fa("۱۰ فروردین", self.T)[0], "2027-03-30")  # a past month rolls to next year
        self.assertIsNone(parse_date_fa("یه وقتی", self.T))

    def test_maybe_is_an_idea(self):
        out = parse_capture("شاید یک باشگاه نزدیک خانه پیدا کنم؟", self.T)
        self.assertEqual(out["tasks"], [])
        self.assertEqual(len(out["notes"]), 1)


class PreferenceTests(unittest.TestCase):
    def test_jalali_weeks_start_on_saturday_with_friday_off(self):
        s = fresh()
        self.assertEqual(s.get_week("2026-09-22")["start"], "2026-09-21")   # Monday
        s.update_preferences(lang="fa", calendar="jalali")
        self.assertEqual(s.get_week("2026-09-22")["start"], "2026-09-19")   # Saturday
        s.create_task(title="Report", due_date="2026-09-25", estimate_min=60)
        plan = ag.week_plan(s, "2026-09-22", today="2026-09-22")
        days = [d["date"] for d in plan["days"]]
        self.assertNotIn("2026-09-25", days)                                 # Friday is off
        self.assertIn("2026-09-24", days)                                    # Thursday is a workday

    def test_bad_preferences_refused(self):
        s = fresh()
        with self.assertRaises(ValidationError):
            s.update_preferences(lang="xx")
        with self.assertRaises(ValidationError):
            s.update_reminders(True, 500, "")
        with self.assertRaises(ValidationError):
            s.update_reminders(True, 10, "25:00")

    def test_persian_basic_mode_replies_in_persian(self):
        s = fresh()
        s.update_preferences(lang="fa", calendar="jalali")
        s.create_task(title="فاکتور", due_date="2026-09-10")
        out = ag.chat(s, "چه کارهایی عقب افتاده؟", {"today": TODAY, "now": None})
        self.assertIn("عقب‌افتاده", out["reply"])
        self.assertIn("شهریور", out["reply"])     # dates shown in the Jalali calendar
        self.assertIn("حالت ساده", out["notice"])

    def test_confirmation_summary_in_persian(self):
        s = fresh()
        s.update_preferences(lang="fa", calendar="jalali")
        t = s.create_task(title="گزارش")
        parked = ag.run_tool(s, "delete_task", {"id": t["id"]}, CTX)
        self.assertEqual(parked["summary"], "حذف کار «گزارش»")


class DayPlanScopeTests(unittest.TestCase):
    def test_tasks_planned_for_a_later_day_stay_there(self):
        s = fresh()
        s.create_task(title="Tomorrow's thing", scheduled_date="2026-09-17", estimate_min=30)
        s.create_task(title="Loose end", estimate_min=30)
        s.create_task(title="Late", scheduled_date="2026-09-15", estimate_min=30)
        titles = [b["title"] for b in ag.day_plan(s, TODAY)["schedule"] if b["type"] == "task"]
        self.assertNotIn("Tomorrow's thing", titles)
        self.assertIn("Loose end", titles)
        self.assertIn("Late", titles)                       # left over from yesterday: still today's business


class TimeAndReminderTests(unittest.TestCase):
    def test_saving_a_day_plan_keeps_start_times(self):
        s = fresh()
        t = s.create_task(title="Deck", estimate_min=60)
        ag.apply_schedule(s, [{"id": t["id"], "to": TODAY, "time": "10:30"}])
        self.assertEqual(s.get_task(t["id"])["scheduled_time"], "10:30")
        s.reschedule_task(t["id"], "2026-09-18")                   # moving the day drops the old time
        self.assertIsNone(s.get_task(t["id"])["scheduled_time"])
        with self.assertRaises(ValidationError):
            s.update_task(t["id"], scheduled_time="7pm")

    def test_reminders_for_the_next_day(self):
        from app import build_reminders
        s = fresh()
        s.create_event("Standup", TODAY, "10:00", "10:15")
        s.create_event("Old", TODAY, "08:00", "08:30")               # already started: no reminder
        t = s.create_task(title="Deck", estimate_min=45)
        ag.apply_schedule(s, [{"id": t["id"], "to": TODAY, "time": "14:00"}])
        rem = build_reminders(s.upcoming(TODAY), TODAY, "09:00", lead_min=10, morning="08:30",
                              lang="en", summary=lambda d: {"tasks": 1, "events": 1, "overdue": 0})
        self.assertEqual([r["at"] for r in rem],
                         ["2026-09-16T09:50", "2026-09-16T13:50", "2026-09-17T08:30"])
        self.assertEqual(rem[0]["title"], "Meeting at 10:00")
        self.assertIn("Deck", rem[1]["body"])
        fa = build_reminders(s.upcoming(TODAY), TODAY, "09:00", lead_min=10, lang="fa")
        self.assertEqual(fa[0]["title"], "جلسه ساعت ۱۰:۰۰")

    def test_calendar_file(self):
        from app import build_ics, plan_items
        s = fresh()
        s.create_event("Client call, part 1; notes", TODAY, "14:00", "15:00")
        t = s.create_task(title="جلسهٔ تیم " + "خیلی مهم " * 10, estimate_min=30)
        ag.apply_schedule(s, [{"id": t["id"], "to": TODAY, "time": "09:30"}])
        up = s.upcoming(TODAY)
        ics = build_ics(plan_items(up["events"], up["tasks"]), lead_min=15, user_key="1")
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n"))
        self.assertIn("SUMMARY:Client call\\, part 1\\; notes", ics)   # commas and semicolons escaped
        self.assertIn("DTSTART:20260916T093000", ics)
        self.assertIn("DTEND:20260916T100000", ics)                      # start plus the 30-minute estimate
        self.assertEqual(ics.count("TRIGGER:-PT15M"), 2)
        self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split("\r\n")))   # folded lines
        again = build_ics(plan_items(up["events"], up["tasks"]), lead_min=15, user_key="1")
        uid = [l for l in ics.split("\r\n") if l.startswith("UID:")]
        self.assertEqual(uid, [l for l in again.split("\r\n") if l.startswith("UID:")])  # stable ids


if __name__ == "__main__":
    unittest.main()
