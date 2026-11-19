"""Optional OpenAI ranking over anonymous, allowlisted work evidence."""

from dataclasses import dataclass
from hashlib import sha256
from http.client import HTTPException
import json
import re
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .codex_rpc import path_key
from .work_signals import MILESTONES


ENDPOINT = "https://api.openai.com/v1/responses"
DATA_POLICY = "https://developers.openai.com/api/docs/guides/your-data"
REQUEST_BYTES = 4000
RUN_BYTES = 20000
OUTPUT_TOKENS = 600
RESPONSE_BYTES = 64 * 1024
PROMPT = (
    "Rank the supplied anonymous work evidence. Select up to 6 useful summary facts and 2 existing follow-up facts. "
    "Select at most 3 supplied merge candidates, only with one fact from each candidate member. "
    "Copy only IDs in the input. Each summary or follow-up item must own its fact. "
    "Commands are execution records, claims are unverified, and hints are already recorded. "
    "Return empty arrays when the supplied evidence does not support a selection."
)
GRADE = {"Verified": "record", "Reported": "claim", "UserConfirmed": "user_confirmation", "Unknown": "unknown"}
KINDS = {kind: kind for kind in ("turn_started", "turn_ended", "command_started", "command_ended", "file_change",
                                 "claim", "confirmation", "follow_up")}
OUTCOMES = {name: name for name in ("success", "failed", "pending")}
MILESTONE_TAGS = {kind: kind for kind in MILESTONES}


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def array_schema(items):
    return {"type": "array", "items": items}


STRING = {"type": "string"}
SELECTION = object_schema({"item_id": STRING, "fact_id": STRING})
SCHEMA = object_schema({
    "summary_lines": array_schema(SELECTION),
    "merge_suggestions": array_schema(object_schema({"candidate_id": STRING, "fact_ids": array_schema(STRING)})),
    "follow_up_hints": array_schema(SELECTION),
})


class ModelError(Exception):
    pass


class RateLimited(ModelError):
    def __init__(self, delay):
        super().__init__("rate_limited")
        self.delay = delay


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Batch:
    body: bytes
    items: dict
    facts: dict
    pairs: dict
    omitted: int

    @property
    def approval(self):
        return sha256(self.body).hexdigest()[:10]

    def cache_key(self, path, namespace, window):
        scope = [path_key(path), namespace, window.period, window.start, window.end, window.zone,
                 self.items, {alias: row["id"] for alias, (_, row) in self.facts.items()}, self.pairs]
        return sha256(self.body + json.dumps(scope, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def wire_body(model, items, candidates):
    payload = {"model": model, "instructions": PROMPT, "store": False, "max_output_tokens": OUTPUT_TOKENS,
               "input": json.dumps({"items": items, "candidates": candidates}, separators=(",", ":")),
               "text": {"format": {"type": "json_schema", "name": "pearl_work_rank", "strict": True, "schema": SCHEMA}}}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def fact_tags(row, item):
    kind = KINDS.get(row["kind"])
    grade = GRADE.get(row["grade"])
    if not kind or not grade or grade == "unknown":
        return None
    if kind == "follow_up" and row["id"] not in item["follow_up"]:
        return None
    milestone = MILESTONE_TAGS.get(row["milestone"])
    if grade == "user_confirmation" and not any(row["id"] in status["evidence_ids"] for status in item["milestones"].get(milestone, [])):
        return None
    tags = {"kind": kind, "grade": grade}
    if milestone:
        tags["milestone"] = milestone
    if outcome := OUTCOMES.get(row["outcome"]):
        tags["outcome"] = outcome
    return tags


def prepare_batch(project, model):
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", model):
        raise ModelError("invalid_model")
    items, facts, pairs = {}, {}, {}
    data = []
    for item in project["work_items"][:12]:
        item_alias = f"i{len(items) + 1}"
        choices = []
        # Preserve reported milestones and recorded next steps when many commands are present.
        rows = sorted(item["evidence"], key=lambda row: row["kind"] not in {"follow_up", "claim", "confirmation"})
        for row in rows:
            if tags := fact_tags(row, item):
                fact_alias = f"f{len(facts) + len(choices) + 1}"
                choices.append((row, {"id": fact_alias, **tags}))
                if len(choices) == 5:
                    break
        if not choices:
            continue
        candidate = {"id": item_alias, "facts": [tags for _, tags in choices]}
        if len(wire_body(model, data + [candidate], [])) > REQUEST_BYTES:
            break
        items[item_alias] = item["id"]
        facts.update({tags["id"]: (item_alias, row) for row, tags in choices})
        data.append(candidate)
    positions = {item: alias for alias, item in items.items()}
    candidates = []
    for suggestion in project["merge_suggestions"][:12]:
        if not all(item in positions for item in suggestion["items"]):
            continue
        aliases = tuple(positions[item] for item in suggestion["items"])
        candidate_alias = f"c{len(pairs) + 1}"
        choice = {"id": candidate_alias, "members": aliases, "reason": "same_title"}
        if len(wire_body(model, data, candidates + [choice])) > REQUEST_BYTES:
            break
        candidates.append(choice)
        pairs[candidate_alias] = aliases
    return Batch(wire_body(model, data, candidates), items, facts, pairs, len(project["work_items"]) - len(items))


def bad_selection():
    raise ModelError("invalid_selection")


def valid_id(value, allowed):
    return isinstance(value, str) and value in allowed


def validate_selection(value, batch):
    limits = {"summary_lines": 6, "merge_suggestions": 3, "follow_up_hints": 2}
    if not isinstance(value, dict) or set(value) != set(limits):
        bad_selection()
    for key, maximum in limits.items():
        rows = value[key]
        if not isinstance(rows, list) or len(rows) > maximum or any(not isinstance(row, dict) for row in rows):
            bad_selection()
        selected = set()
        for row in rows:
            if key == "merge_suggestions":
                if set(row) != {"candidate_id", "fact_ids"} or not valid_id(row["candidate_id"], batch.pairs):
                    bad_selection()
                ids = row["fact_ids"]
                if not isinstance(ids, list) or len(ids) != 2 or not all(valid_id(ref, batch.facts) for ref in ids):
                    bad_selection()
                selected_id = row["candidate_id"]
                if {batch.facts[ref][0] for ref in ids} != set(batch.pairs[selected_id]):
                    bad_selection()
            else:
                if set(row) != {"item_id", "fact_id"} or not valid_id(row["fact_id"], batch.facts):
                    bad_selection()
                selected_id = row["fact_id"]
                owner, fact = batch.facts[selected_id]
                if row["item_id"] != owner or (key == "follow_up_hints") != (fact["kind"] == "follow_up"):
                    bad_selection()
            if selected_id in selected:
                bad_selection()
            selected.add(selected_id)
    return value


def project_selection(selection, batch):
    projected = {}
    for key in ("summary_lines", "follow_up_hints"):
        projected[key] = []
        for row in selection[key]:
            _, fact = batch.facts[row["fact_id"]]
            projected[key].append({"item_id": batch.items[row["item_id"]], "evidence_id": fact["id"],
                                   "label": fact["label"], "grade": fact["grade"]})
    projected["merge_suggestions"] = [
        {"items": [batch.items[alias] for alias in batch.pairs[row["candidate_id"]]], "grade": "Inferred",
         "evidence_ids": [batch.facts[alias][1]["id"] for alias in row["fact_ids"]], "reason": "聊天标题相同，待人工核对"}
        for row in selection["merge_suggestions"]
    ]
    return projected


def bounded_json(raw):
    if len(raw) > RESPONSE_BYTES:
        raise ModelError("oversized_response")
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise ModelError("invalid_response") from None


def decode_response(raw):
    wrapper = bounded_json(raw)
    if not isinstance(wrapper, dict) or not isinstance(wrapper.get("output"), list):
        raise ModelError("invalid_response")
    if wrapper.get("status") != "completed":
        raise ModelError("incomplete_response")
    content = []
    for entry in wrapper["output"]:
        if not isinstance(entry, dict):
            raise ModelError("invalid_response")
        if entry.get("type") == "reasoning":
            continue
        if entry.get("type") != "message" or entry.get("role") != "assistant" or not isinstance(entry.get("content"), list):
            raise ModelError("invalid_response")
        content.extend(entry["content"])
    if any(isinstance(row, dict) and row.get("type") == "refusal" for row in content):
        raise ModelError("refusal")
    if len(content) != 1 or not isinstance(content[0], dict) or content[0].get("type") != "output_text":
        raise ModelError("invalid_response")
    raw_text = content[0].get("text")
    if not isinstance(raw_text, str):
        raise ModelError("invalid_response")
    usage = wrapper.get("usage")
    tokens = {key: usage[key] for key in ("input_tokens", "output_tokens")
              if isinstance(usage, dict) and type(usage.get(key)) is int and usage[key] >= 0}
    return bounded_json(raw_text), tokens


def openai_request(body, api_key):
    request = Request(ENDPOINT, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=12) as response:
            return decode_response(response.read(RESPONSE_BYTES + 1))
    except HTTPError as error:
        try:
            if error.code == 429:
                value = error.headers.get("Retry-After", "1")
                delay = int(value) if re.fullmatch(r"[0-9]{1,3}", value) else 13
                raise RateLimited(delay) from None
            raise ModelError(f"http_{error.code}") from None
        finally:
            error.close()
    except (URLError, OSError, ValueError, HTTPException):
        raise ModelError("transport_error") from None


def request_selection(batch, api_key, remaining, guard):
    cost = len(batch.body)
    used = 0
    for attempt in range(2):
        if used + cost > remaining:
            return None, {}, used, "request_budget"
        guard()
        used += cost
        try:
            selection, usage = openai_request(batch.body, api_key)
            return validate_selection(selection, batch), usage, used, None
        except RateLimited as error:
            if attempt or error.delay > 2 or used + cost > remaining:
                return None, {}, used, "rate_limited"
            sleep(error.delay)
        except ModelError as error:
            return None, {}, used, str(error)
    raise RuntimeError("unreachable retry state")


def enhance(report, model, *, namespace, window, credentials, approve, store, generation):
    remaining = RUN_BYTES
    for project in report["projects"]:
        state = {"status": "offline"}
        project["ai"] = state
        if project["status"] not in {"complete", "empty"}:
            state["reason"] = "incomplete_history"
            continue
        try:
            batch = prepare_batch(project, model)
        except ModelError as error:
            state["reason"] = str(error)
            continue
        state["selected_items"] = len(batch.items)
        state["omitted_items"] = batch.omitted
        if not batch.items:
            state["reason"] = "no_supported_evidence"
            continue
        decision = approve(project, batch, remaining)
        if decision != "send":
            state["reason"] = decision
            continue

        key = batch.cache_key(project["path"], namespace, window)
        cached = store.ai_cached(key, generation)
        if cached is not None:
            try:
                selection = validate_selection(cached, batch)
            except ModelError:
                state["reason"] = "invalid_cached_selection"
            else:
                state.update(status="cached", **project_selection(selection, batch))
            continue
        if not credentials or not re.fullmatch(r"[!-~]{1,512}", credentials):
            state["reason"] = "missing_credentials"
            continue

        selection, usage, used, reason = request_selection(batch, credentials, remaining, lambda: store.check_generation(generation))
        remaining -= used
        if reason:
            state["reason"] = reason
            continue
        store.save_ai(project["path"], key, selection, generation)
        state.update(status="complete", usage=usage, **project_selection(selection, batch))
