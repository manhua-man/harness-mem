"""Surface explicit source conditions before a manual memory write is staged."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import re
from typing import Any, Iterable

from harness_mem.commands.evidence_admission import resolve_repository_evidence_path
from harness_mem.core.schemas.assimilation import AgentKnowledgeReview
from harness_mem.core.schemas.evidence import EvidenceBinding, EvidenceRef
from harness_mem.mcp.distill_projection import _parse_exchanges, render_distill_exchange_windows


_SENTENCE = re.compile(r"[。！？!?;；\n]+|(?<=\.)\s+(?=[A-Z])")
_CONDITION = re.compile(
    r"(?:即使|即便|即便是|除非|只有|仅当|唯有|前提是|"
    r"(?:缺少|没有|不存在|缺乏|未经|无法|未取得|未通过|失败|遇到)[^，,。:：]{1,45}(?:时|情况下)|"
    r"\beven (?:if|when|without)\b|\bunless\b|\bonly (?:if|when|after)\b|"
    r"\bwithout\b[^,]{4,65},|\bif\b[^,]{4,85},\s*(?:then\s+)?\w)",
    re.IGNORECASE,
)
_OPERATIONAL_DETAIL = re.compile(
    r"(?:先|首先)[^，,。:：]{3,90}[，,]?\s*(?:然后|接着|再|之后|才)[^，,。:：]{2,90}|"
    r"\bfirst\b.{3,90}\b(?:then|before)\b|"
    r"(?:排除|剔除|过滤|except|exclude|filter out).{2,80}\d|"
    r"(?:分别|依次|逐个|分别由|负责)[^。]{3,90}(?:与|、|及|和|分别)|"
    r"(?:下载|download).{3,70}(?:保存|写入|落盘|store|persist)",
    re.IGNORECASE,
)
_UI_ACTION = re.compile(
    r"(?:await\s+)?[\w.\[\]]+(?:\([^\n;]*?\))?\.(?:click|press|fill|tap|selectOption)\([^\n;]*\);?"
)
_SH_ACTION = re.compile(
    r"^(?:(?:\.venv[/\\]Scripts[/\\])?(?:python(?:\.exe)?|uv)\s+(?:-m\s+)?"
    r"[\w./-]+|(?:npx|npm|pnpm|yarn|pytest|node|cargo|cmake|go|dotnet)\s+[\w./-]+|"
    r"git\s+(?:push|clone|commit|checkout|switch|merge|rebase)\b)",
    re.IGNORECASE,
)
_TERM = re.compile(r"[a-z0-9][a-z0-9_.-/]*|[\u3400-\u9fff]+", re.IGNORECASE)
_NEGATION = re.compile(r"不得|不能|未经|不可|尚未|仍未|没有|\b(?:not|never|without|unless)\b", re.IGNORECASE)
_COMMON = {"可以", "使用", "问题", "情况", "需要", "必须", "不能", "不要", "如果", "这个", "当前",
           "when", "then", "only", "does", "that", "with", "without", "this", "have", "from", "must"}
_WRITES = {"add", "refine", "replace", "confirm"}
_DIFF_ADDITION = re.compile(r"^\+(?!\+)")


class ConditionReviewRequired(ValueError):
    def __init__(self, findings: list[dict[str, Any]]):
        super().__init__("source_conditions_need_review")
        self.findings = findings


def bind_review_evidence(
    *, review: AgentKnowledgeReview, statement: str, refs: list[EvidenceRef],
    transcript: str, project_root: str | None, native: dict | None = None,
) -> list[EvidenceRef]:
    """Check exact source text before any candidate can be staged."""
    if review.evidence is None:
        if review.operations:
            raise ValueError("a native operation must also bind the originating knowledge claim")
        return refs
    if not statement or any(phrase not in statement for phrase in review.conditions):
        raise ValueError("review conditions must be present in the submitted knowledge")
    if review.undecided_state and review.undecided_state not in statement:
        raise ValueError("review undecided state must be present in the submitted knowledge")
    required = {("claim", statement), *(("condition", phrase) for phrase in review.conditions)}
    if review.undecided_state:
        required.add(("undecided_state", review.undecided_state))
    covered: set[tuple[str, str]] = set()
    excerpts: dict[tuple[int, int | None], str] = {}
    bindings: list[list[EvidenceBinding]] = [[] for _ in refs]
    for item in review.evidence:
        if item.target == "condition":
            destination = item.condition
        else:
            if item.condition is not None:
                raise ValueError("only a condition binding may name a condition")
            destination = statement if item.target == "claim" else review.undecided_state
        if destination is None or (item.target, destination) not in required or item.ref > len(refs):
            raise ValueError("review evidence must name a submitted claim, condition or state and its typed reference")
        ref = refs[item.ref - 1]
        key = (item.ref, item.message_index)
        if key not in excerpts:
            excerpts[key] = _reference_text(ref, item.message_index, transcript, project_root)
        source = excerpts[key]
        offset = source.find(item.quote)
        if not item.quote.strip() or offset < 0 or source.find(item.quote, offset + 1) >= 0:
            raise ValueError(f"review evidence ref {item.ref} needs an exact, uniquely located source quote")
        binding = EvidenceBinding(
            target=item.target, target_sha256=sha256(destination.encode()).hexdigest(),
            quote_sha256=sha256(item.quote.encode()).hexdigest(),
            message_index=item.message_index, start=offset, end=offset + len(item.quote),
        )
        if binding not in bindings[item.ref - 1]:
            bindings[item.ref - 1].append(binding)
        covered.add((item.target, destination))
    if required != covered or any(not items for items in bindings):
        raise ValueError("bind the claim, every retained condition or undecided state, and each cited source")
    if review.operations:
        _bind_operations(review, statement, bindings, native or {})
    return [ref.model_copy(update={"bindings": items}) for ref, items in zip(refs, bindings)]


def _bind_operations(review: AgentKnowledgeReview, statement: str,
                     bindings: list[list[EvidenceBinding]], native: dict) -> None:
    if native.get("status") != "available":
        raise ValueError("original native call and result could not be reopened")
    by_line = {item["native_line"]: item for item in native["records"]}
    for item in review.operations:
        call, result = by_line.get(item.call_line), by_line.get(item.result_line)
        if (item.ref > len(bindings) or item.phrase not in statement
                or not any(binding.target == "claim" for binding in bindings[item.ref - 1])
                or not call or not result or item.call_line >= item.result_line
                or call["call_id"] != item.call_id or result["call_id"] != item.call_id
                or call["type"] not in {"function_call", "custom_tool_call"}
                or result["type"] not in {"function_call_output", "custom_tool_call_output"}):
            raise ValueError("operation needs the original paired call and result for the submitted claim phrase")
        for quote, record in ((item.call_quote, call), (item.result_quote, result)):
            if not quote.strip() or record["text"].count(quote) != 1:
                raise ValueError("operation evidence needs exact, unique call and result passages")
        name = str(call.get("name") or "").casefold()
        command = item.call_quote.strip()
        try:
            arguments = json.loads(call["text"])
        except (TypeError, ValueError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        script = arguments.get("code")
        shell = arguments.get("cmd") or arguments.get("command")
        if item.observed_as == "interaction" and not (
            re.search(r"(?:^|[_.])(?:click|press|fill|tap|select_option)$", name)
            or "node_repl" in name and isinstance(script, str)
            and script.strip() == command and _UI_ACTION.fullmatch(command)
        ):
            raise ValueError("native evidence shows no direct interaction in the cited action")
        if item.observed_as == "execution" and not (
            isinstance(shell, str) and shell.strip().startswith(command) and _SH_ACTION.match(command)
        ):
            raise ValueError("native evidence shows no supported command execution in the cited action")
        offset = result["text"].index(item.result_quote)
        bindings[item.ref - 1].append(EvidenceBinding(
            target="operation", target_sha256=sha256(item.phrase.encode()).hexdigest(),
            quote_sha256=sha256(item.result_quote.encode()).hexdigest(),
            start=offset, end=offset + len(item.result_quote),
            native_trace={
                "observed_as": item.observed_as, "native_sha256": native["native_sha256"],
                "call_line": item.call_line, "result_line": item.result_line,
                "call_quote_sha256": sha256(item.call_quote.encode()).hexdigest(),
            },
        ))


def _reference_text(
    ref: EvidenceRef, message_index: int | None, transcript: str, project_root: str | None,
) -> str:
    if ref.kind == "repository" and ref.locator and message_index is None:
        path, _ = resolve_repository_evidence_path(ref.locator, project_root)
        if path is None:
            raise ValueError("review evidence repository path is unavailable")
        try:
            raw = path.read_bytes()
            if sha256(raw).hexdigest() == ref.content_sha256:
                return raw.decode("utf-8")
        except (UnicodeError, OSError) as exc:
            raise ValueError("review evidence repository text is unavailable") from exc
        raise ValueError("review evidence repository version changed")
    if ref.kind in {"source_report", "user_statement"} and ref.exchange_index and message_index:
        windows = render_distill_exchange_windows(transcript, [ref.exchange_index])
        if not windows or windows[0]["content_sha256"] != ref.content_sha256:
            raise ValueError("review evidence exchange version changed")
        role = "user" if ref.kind == "user_statement" else ref.role
        if role in {"user", "assistant"}:
            messages = _parse_exchanges(transcript)[1][ref.exchange_index - 1][role]
            if message_index <= len(messages):
                return str(messages[message_index - 1])
    raise ValueError("review evidence requires a repository file or the cited authored exchange and message index")


def _terms(text: str) -> set[str]:
    terms = set()
    for term in _TERM.findall(text.casefold()):
        if term.isascii():
            if len(term) >= 4:
                terms.add(term)
        else:
            terms.update(term[i:i + 2] for i in range(len(term) - 1))
    return terms - _COMMON


def _sentences(text: str, *, details: bool = False) -> Iterable[tuple[int, str, set[str]]]:
    in_fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for part in _SENTENCE.split(line):
            part = part.strip(" \t-*>#")
            if 16 <= len(part) <= 320 and (_CONDITION.search(part) or details and _OPERATIONAL_DETAIL.search(part)):
                yield number, part, _terms(part)


def _retained(sentence: str, terms: set[str], output: str) -> bool:
    if _literal_retained(sentence, output):
        return True
    # A paraphrase must carry both the subject and the condition. Merely
    # repeating topic terms in the proposed knowledge cannot settle the check.
    return any(bool(_NEGATION.search(reworded)) == bool(_NEGATION.search(sentence))
               and len(terms & actual) * 5 >= len(terms) * 4
               for _, reworded, actual in _sentences(output, details=True))


def _literal_retained(sentence: str, output: str) -> bool:
    return "".join(_TERM.findall(sentence.casefold())) in "".join(_TERM.findall(output.casefold()))


def _native_topic_matches(clause: str, topic: str, *, changed_line: bool, table_row: bool) -> bool:
    """Require a shared subject phrase before blocking on a native excerpt."""
    source = _TERM.findall(clause.casefold())
    target = _TERM.findall(topic.casefold())
    # Added patch text is already localized to a change. An incidental
    # phrase from a whole document or tool report needs a stronger anchor.
    width = 4 if changed_line else 5
    source_runs = [term for term in source if not term.isascii()]
    for term in target:
        if term.isascii():
            continue
        for start in range(len(term) - width + 1):
            anchor = term[start:start + width]
            if not any(anchor in run for run in source_runs):
                continue
            # A table cell can repeat a short case label while describing a
            # different outcome. Require another shared term in that cell.
            if not table_row or _terms(clause.replace(anchor, " ")) & _terms(topic):
                return True
    source_pairs = set(zip(source, source[1:]))
    return any(left.isascii() and right.isascii() and len(left) >= 4 and len(right) >= 4
               and left not in _COMMON and right not in _COMMON and (left, right) in source_pairs
               for left, right in zip(target, target[1:]))


def _evidence_at(point: dict, origin: dict, item: dict | None = None) -> bool:
    refs = point.get("verification_refs")
    review = point.get("review")
    if not isinstance(refs, list) or not isinstance(review, dict):
        return False
    for citation in ([item] if item is not None else review.get("evidence") or []):
        if not isinstance(citation, dict):
            continue
        index = citation.get("ref")
        if type(index) is not int or not 1 <= index <= len(refs):
            continue
        ref = refs[index - 1]
        if not isinstance(ref, dict):
            continue
        if "repository_file" in origin:
            if ref.get("kind") == "repository" and ref.get("locator") == origin["repository_file"]:
                return True
        elif (ref.get("kind") in {"user_statement", "source_report"}
              and ref.get("exchange_index") == origin["exchange_index"]
              and (ref.get("role") or ("user" if ref["kind"] == "user_statement" else None)) == origin["role"]
              and citation.get("message_index") == origin["message"]):
            return True
    return False


def _explicitly_bound(point: dict, output: str, origin: dict, sentence: str) -> bool:
    review = point.get("review")
    if not isinstance(review, dict):
        return False
    for item in review.get("evidence") or []:
        if not isinstance(item, dict) or item.get("target") != "condition":
            continue
        phrase, quote = item.get("condition"), item.get("quote")
        if (not isinstance(phrase, str) or not phrase.strip() or phrase not in output
                or phrase not in (review.get("conditions") or [])
                or not isinstance(quote, str) or sentence not in quote):
            continue
        if _evidence_at(point, origin, item):
            return True
    return False


def review_source_conditions(
    *, revision: str, transcript: str, project_root: str | None,
    points: list[dict[str, Any]], exclusions: dict[str, str],
    native_records: list[dict[str, Any]] | None = None,
) -> None:
    """Compare checked source clauses with proposed writing points, before any write.

    Check explicit conditions throughout the conversation, plus operational
    details from a cited message or file. The Agent decides which details apply.
    """
    proposals = [point for point in points if isinstance(point, dict)
                 and point.get("assimilation_disposition") in _WRITES and point.get("review")]
    if not proposals:
        return
    outputs = [(point, str(point.get("content") or ""),
                _terms(str(point.get("canonical_title") or "") + " " + str(point.get("content") or "")))
               for point in proposals]
    findings: dict[str, tuple[int, dict[str, Any]]] = {}

    def check(
        text: str, origin: dict[str, Any], candidates: list[tuple[dict[str, Any], str, set[str]]],
    ) -> None:
        cited = [item for item in candidates if _evidence_at(item[0], origin)]
        for line, sentence, terms in _sentences(text, details=bool(cited)):
            conditional = bool(_CONDITION.search(sentence))
            compared = candidates if conditional else cited
            relevance = max((len(terms & topic) for _, _, topic in compared), default=0)
            if relevance < (2 if conditional else 3) or any(
                (_retained(sentence, terms, output) if conditional else _literal_retained(sentence, output))
                or _explicitly_bound(point, output, origin, sentence)
                for point, output, _ in compared
            ):
                continue
            key = sha256(f"{revision}\n{origin}\n{line}\n{sentence}".encode()).hexdigest()[:24]
            if str(exclusions.get(key, "")).strip():
                continue
            findings[key] = (relevance, {"id": key, **origin, "line": line,
                                         "kind": "condition" if conditional else "operational_detail",
                                         "condition": sentence})

    _, exchanges, _ = _parse_exchanges(transcript)
    for index, exchange in enumerate(exchanges, 1):
        for role in ("user", "assistant"):
            for message, content in enumerate(exchange[role], 1):
                check(content, {"exchange_index": index, "role": role, "message": message}, outputs)

    repositories: dict[tuple[str, str], list[tuple[dict[str, Any], str, set[str]]]] = {}
    for item in outputs:
        for ref in item[0].get("verification_refs") or []:
            if isinstance(ref, dict) and ref.get("kind") == "repository":
                locator = ref.get("locator")
                digest = ref.get("content_sha256")
                if isinstance(locator, str) and isinstance(digest, str):
                    repositories.setdefault((locator, digest), []).append(item)
    for (locator, digest), candidates in repositories.items():
        path, _ = resolve_repository_evidence_path(locator, project_root)
        if path is None:
            continue  # Normal evidence admission reports the invalid reference.
        try:
            with path.open("rb") as stream:
                raw = stream.read(262145)
            if len(raw) <= 262144 and sha256(raw).hexdigest() == digest:
                check(raw.decode("utf-8"), {"repository_file": locator}, candidates)
        except (OSError, UnicodeError):
            continue

    if native_records:
        from harness_mem.commands.native_review_questions import (
            is_native_table_row, native_question_clauses, native_review_questions,
        )

        native_topics = []
        for point, output, topic in outputs:
            review = point["review"]
            text = f"{point.get('canonical_title') or ''} {output}"
            operations = [item for item in review.get("operations") or () if isinstance(item, dict)]
            native_topics.append((output, text, topic, operations))

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for finding in native_review_questions(native_records, revision):
            # The same added line can be visible in a patch and subsequent
            # readbacks. Keep every original location for quote verification.
            grouped[finding["condition"]].append(finding)
        for passage, occurrences in grouped.items():
            if any(str(exclusions.get(item["id"], "")).strip() for item in occurrences):
                continue
            finding = occurrences[0]
            clauses = native_question_clauses(passage, finding["kind"])
            changed_line = bool(_DIFF_ADDITION.match(passage))
            table_row = is_native_table_row(passage)
            clause_terms = [(clause, _terms(clause)) for clause in clauses]
            relevance = 0
            for output, text, topic, operations in native_topics:
                if any(all(item.get(key) == occurrence[key] for key in ("call_id", "call_line", "result_line"))
                       and isinstance(item.get(occurrence["quote_field"]), str)
                       and passage in item[occurrence["quote_field"]]
                       and isinstance(item.get("phrase"), str) and item["phrase"].strip()
                       and item["phrase"] in output
                       for item in operations for occurrence in occurrences):
                    break
                for clause, terms in clause_terms:
                    if _native_topic_matches(clause, text, changed_line=changed_line, table_row=table_row):
                        relevance = max(relevance, len(terms & topic))
            else:
                if relevance >= 2:
                    findings[finding["id"]] = (relevance, {**finding, "source": "native_tool_record"})

    missing = sorted(findings.values(), key=lambda item: -item[0])
    if missing:
        raise ConditionReviewRequired([finding for _, finding in missing[:16]])
