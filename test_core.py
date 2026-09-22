"""Tests for the planner core. Run with:  python -m unittest discover tests
(No test framework to install; this uses the standard library.)
"""
import json
import unittest

from planner_core import agent as ag
from planner_core import providers as pv
from planner_core.capture import parse_capture, parse_date
from planner_core.planning import classify, free_windows, plan_day, plan_week
from planner_core.store import Store, ValidationError, connect

TODAY = "2026-09-16"  # a Wednesday
CTX = {"today": TODAY, "now": None}


def fresh():
    return Store(connect(":memory:"))


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


if __name__ == "__main__":
    unittest.main()
