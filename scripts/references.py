#!/usr/bin/env python3
"""Search the development reference library, or validate its catalog."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.json"

SCHEMA_VERSION = 1
KINDS = {
    "documentation",
    "skill",
    "skill+mcp",
    "mcp+cli",
    "mcp",
    "api",
    "service",
    "directory",
    "toolkit",
}
STATUSES = {"verified", "needs_setup", "reference_only", "caution", "unavailable"}
REQUIRED_FIELDS = [
    "id",
    "name",
    "kind",
    "categories",
    "tasks",
    "aliases",
    "homepage",
    "access",
    "setup",
    "cost",
    "license",
    "status",
    "last_verified",
    "evidence",
    "notes",
]
CATEGORY_COUNT = 12
ENTRY_RANGE = (1, 100)

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SECRET_PATTERNS = [
    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\."),
]
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class CatalogError(ValueError):
    """Raised when the catalog cannot be read or parsed."""


def load_catalog(path: Path | None = None) -> dict:
    source = path or CATALOG
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"无法读取 {source}：{exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{source.name} 不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogError(f"{source.name} 顶层必须是对象")
    return payload


def _walk_strings(value, trail="$"):
    if isinstance(value, str):
        yield trail, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{trail}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{trail}[{index}]")


def _parse_date(text) -> date | None:
    if not isinstance(text, str) or not DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def validate_catalog(payload: dict) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version 必须为 1")
    updated = _parse_date(payload.get("updated_at"))
    if updated is None:
        errors.append("updated_at 必须是 YYYY-MM-DD")

    categories = payload.get("categories")
    known_categories: dict[str, str] = {}
    if not isinstance(categories, list):
        errors.append("categories 必须是数组")
        categories = []
    if len(categories) != CATEGORY_COUNT:
        errors.append(f"categories 必须有 {CATEGORY_COUNT} 类，当前 {len(categories)} 类")
    for index, category in enumerate(categories):
        if not isinstance(category, dict):
            errors.append(f"categories[{index}] 必须是对象")
            continue
        cid = category.get("id")
        cname = category.get("name")
        if not isinstance(cid, str) or not ID_RE.match(cid):
            errors.append(f"categories[{index}] 的 id 不合法：{cid!r}")
        elif cid in known_categories:
            errors.append(f"重复分类 id：{cid}")
        if not isinstance(cname, str) or not cname.strip():
            errors.append(f"categories[{index}] 的 name 不能为空")
        elif cid:
            known_categories[cid] = cname
        description = category.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"categories[{index}] 缺少 description")

    entries = payload.get("entries")
    if not isinstance(entries, list):
        errors.append("entries 必须是数组")
        entries = []
    low, high = ENTRY_RANGE
    if not low <= len(entries) <= high:
        errors.append(f"entries 必须有 {low}-{high} 条，当前 {len(entries)} 条")

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{index}] 必须是对象")
            continue
        entry_id = entry.get("id") if isinstance(entry.get("id"), str) else f"index:{index}"
        missing = [field for field in REQUIRED_FIELDS if field not in entry]
        if missing:
            errors.append(f"{entry_id}: 缺少 {', '.join(missing)}")
        extra = sorted(set(entry) - set(REQUIRED_FIELDS))
        if extra:
            errors.append(f"{entry_id}: 出现未定义字段 {', '.join(extra)}")
        if isinstance(entry.get("id"), str):
            if not ID_RE.match(entry["id"]):
                errors.append(f"{entry_id}: id 只能是小写字母、数字与连字符")
            if entry_id in seen:
                errors.append(f"重复 id：{entry_id}")
            seen.add(entry_id)
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            errors.append(f"{entry_id}: name 不能为空")
        if entry.get("kind") not in KINDS:
            errors.append(f"{entry_id}: kind 必须属于 {sorted(KINDS)}")
        if entry.get("status") not in STATUSES:
            errors.append(f"{entry_id}: status 必须属于 {sorted(STATUSES)}")

        for field in ("tasks", "aliases", "evidence"):
            value = entry.get(field)
            if field in entry and not isinstance(value, list):
                errors.append(f"{entry_id}: {field} 必须是数组")
            elif isinstance(value, list):
                if not value:
                    errors.append(f"{entry_id}: {field} 不能为空")
                for item in value:
                    if not isinstance(item, str) or not item.strip():
                        errors.append(f"{entry_id}: {field} 含空项")

        cats = entry.get("categories")
        if isinstance(cats, list):
            if not cats:
                errors.append(f"{entry_id}: categories 不能为空")
            for cat in cats:
                if cat not in known_categories:
                    errors.append(f"{entry_id}: 未知分类 {cat!r}")
        elif "categories" in entry:
            errors.append(f"{entry_id}: categories 必须是数组")

        homepage = entry.get("homepage")
        if isinstance(homepage, str):
            parsed = urlparse(homepage)
            if parsed.scheme != "https" or not parsed.netloc or " " in homepage:
                errors.append(f"{entry_id}: homepage 必须是 https URL")
        elif "homepage" in entry:
            errors.append(f"{entry_id}: homepage 必须是字符串")

        for field in ("access", "setup", "cost", "license", "notes"):
            value = entry.get(field)
            if field in entry and (not isinstance(value, str) or not value.strip()):
                errors.append(f"{entry_id}: {field} 不能为空")

        verified = _parse_date(entry.get("last_verified"))
        if verified is None:
            errors.append(f"{entry_id}: last_verified 必须是 YYYY-MM-DD")
        elif updated and verified > updated:
            errors.append(f"{entry_id}: last_verified 晚于 updated_at")

        evidence = entry.get("evidence")
        if isinstance(evidence, list) and evidence:
            joined = " ".join(item for item in evidence if isinstance(item, str))
            if "http" not in joined:
                errors.append(f"{entry_id}: evidence 至少需要一条带 URL 的来源")
            if isinstance(entry.get("last_verified"), str) and entry["last_verified"] not in joined:
                errors.append(f"{entry_id}: evidence 需要带上核对日期 {entry['last_verified']}")

    for trail, text in _walk_strings(payload):
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"{trail}: 疑似包含密钥或私钥，不应写入目录")
                break
    return errors


def _flush(tokens, cjk_buffer, ascii_buffer):
    if cjk_buffer:
        tokens.append("".join(cjk_buffer))
        cjk_buffer.clear()
    if ascii_buffer:
        token = "".join(ascii_buffer).strip("._-/")
        if token:
            tokens.append(token)
        ascii_buffer.clear()


def tokenize(query: str) -> list[str]:
    tokens: list[str] = []
    cjk_buffer: list[str] = []
    ascii_buffer: list[str] = []
    for char in query:
        if CJK_RE.match(char):
            if ascii_buffer:
                _flush(tokens, cjk_buffer, ascii_buffer)
            cjk_buffer.append(char)
        elif char.isalnum() or char in "+#._-/":
            if cjk_buffer:
                _flush(tokens, cjk_buffer, ascii_buffer)
            ascii_buffer.append(char)
        else:
            _flush(tokens, cjk_buffer, ascii_buffer)
    _flush(tokens, cjk_buffer, ascii_buffer)
    return [token for token in tokens if token]


def query_terms(query: str) -> list[tuple[str, int, bool]]:
    terms: list[tuple[str, int, bool]] = []
    for token in tokenize(query.casefold()):
        if CJK_RE.search(token):
            if len(token) >= 2:
                terms.append((token, 6, True))
                terms.extend((token[index:index + 2], 1, False) for index in range(len(token) - 1))
            else:
                terms.append((token, 3, True))
        else:
            terms.append((token, 6, True))
    unique: list[tuple[str, int, bool]] = []
    seen: set[tuple[str, bool]] = set()
    for term in terms:
        key = (term[0], term[2])
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique


def _matches(text: str, term: str) -> bool:
    if CJK_RE.search(term):
        return term in text
    pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _entry_text(entry: dict, category_names: dict[str, str]) -> list[tuple[str, int]]:
    cats = [category_names.get(cat, cat) for cat in entry.get("categories", [])]
    return [
        (str(entry.get("id", "")), 5),
        (str(entry.get("name", "")), 6),
        (" ".join(entry.get("aliases", [])), 6),
        (" ".join(entry.get("tasks", [])), 5),
        (" ".join([*entry.get("categories", []), *cats]), 4),
        (str(entry.get("kind", "")), 2),
        (str(entry.get("access", "")), 2),
        (str(entry.get("setup", "")), 1),
        (str(entry.get("notes", "")), 1),
    ]


def score_entry(entry: dict, terms: list[tuple[str, int, bool]], category_names: dict[str, str]):
    fields = [(text.casefold(), weight) for text, weight in _entry_text(entry, category_names)]
    total = 0
    exact_hits = 0
    partial_hits = 0
    exact_terms: list[str] = []
    partial_terms: list[str] = []
    for term, weight, exact in terms:
        hits = sum(field_weight for text, field_weight in fields if _matches(text, term))
        if not hits:
            continue
        total += weight * hits
        if exact:
            exact_hits += 1
            exact_terms.append(term)
        else:
            partial_hits += 1
            partial_terms.append(term)
    return total, exact_hits, partial_hits, exact_terms, partial_terms


def resolve_category(filters: list[str], categories: list[dict]) -> list[str]:
    by_name = {c["name"].casefold(): c["id"] for c in categories if isinstance(c, dict)}
    by_id = {c["id"]: c["id"] for c in categories if isinstance(c, dict) and isinstance(c.get("id"), str)}
    resolved: list[str] = []
    for raw in filters:
        for value in raw.split(","):
            key = value.strip()
            if not key:
                continue
            cid = by_id.get(key) or by_name.get(key.casefold())
            if cid is None:
                allowed = "、".join(f"{c['id']}({c['name']})" for c in categories)
                raise ValueError(f"未知分类 {key!r}；可用分类：{allowed}")
            if cid not in resolved:
                resolved.append(cid)
    return resolved


def search(payload: dict, query: str, category_filters: list[str], kind_filters: list[str], limit: int):
    categories = [c for c in payload.get("categories", []) if isinstance(c, dict)]
    category_names = {c["id"]: c["name"] for c in categories}
    resolved = resolve_category(category_filters, categories)
    kinds = [k.strip() for raw in kind_filters for k in raw.split(",") if k.strip()]
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError(f"未知 kind {kind!r}；可用：{'、'.join(sorted(KINDS))}")

    terms = query_terms(query)
    results = []
    for entry in payload.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if resolved and not set(resolved) & set(entry.get("categories", [])):
            continue
        if kinds and entry.get("kind") not in kinds:
            continue
        total, exact_hits, partial_hits, exact_terms, partial_terms = score_entry(entry, terms, category_names)
        if not exact_hits and partial_hits < 2:
            continue
        results.append((total, entry, exact_terms, partial_terms))
    results.sort(key=lambda row: (-row[0], str(row[1].get("name", ""))))
    selected = results[:limit]
    return {
        "query": query,
        "filters": {"category": resolved, "kind": kinds},
        "limit": limit,
        "count": len(results),
        "returned": len(selected),
        "results": [
            {
                **entry,
                "category_names": [category_names.get(c, c) for c in entry.get("categories", [])],
                "match": {"score": total, "exact_terms": exact_terms, "partial_terms": partial_terms},
            }
            for total, entry, exact_terms, partial_terms in selected
        ],
        "note": "" if selected else "没有匹配条目；未编造结果。可换用任务名、英文名或分类过滤再查。",
    }


def render_human(result: dict) -> str:
    lines = [
        f"查询：{result['query']}",
        f"命中 {result['count']} 条，显示 {result['returned']} 条（上限 {result['limit']}）",
    ]
    if result["note"]:
        lines.append(result["note"])
        return "\n".join(lines)
    for index, entry in enumerate(result["results"], 1):
        lines.append("")
        lines.append(f"{index}. {entry['name']} ({entry['kind']}) [{entry['status']}]")
        lines.append(f"   分类：{' / '.join(entry['category_names'])}")
        lines.append(f"   能做什么：{'；'.join(entry['tasks'][:3])}")
        lines.append(f"   怎么用：{entry['access']}")
        lines.append(f"   配置条件：{entry['setup']}")
        lines.append(f"   费用 / 许可：{entry['cost']} / {entry['license']}")
        lines.append(f"   来源：{entry['homepage']}（核对 {entry['last_verified']}）")
        lines.append(f"   状态依据：{entry['evidence'][0]}")
    lines.append("")
    lines.append("状态说明：verified=官方入口已核实（不代表已登录或已调用云资源）；needs_setup=需配置后才能用；reference_only=只读资料；caution=有风险或部分不可用；unavailable=当前不可用。")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="references.py",
        description="开发参考库检索与目录校验（标准库实现，无网络请求）。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("search", help="按自然语言问题检索条目")
    sp.add_argument("query", help="自然语言问题，例如 'Supabase 数据库权限'")
    sp.add_argument("--category", action="append", default=[], help="按分类过滤，可重复或逗号分隔，接受 id 或中文名")
    sp.add_argument("--kind", action="append", default=[], help="按类型过滤，可重复或逗号分隔")
    sp.add_argument("--limit", type=int, default=3, help="返回条数，1-5，默认 3")
    sp.add_argument("--json", action="store_true", help="输出 JSON")
    sp.add_argument("--catalog", default=None, help="指定 catalog.json 路径")

    cp = sub.add_parser("check", help="校验 catalog.json")
    cp.add_argument("--json", action="store_true", help="输出 JSON")
    cp.add_argument("--catalog", default=None, help="指定 catalog.json 路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    catalog_path = Path(args.catalog) if args.catalog else None

    try:
        payload = load_catalog(catalog_path)
    except CatalogError as exc:
        if args.json:
            print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        else:
            print(f"错误：{exc}", file=sys.stderr)
        return 1

    if args.command == "check":
        errors = validate_catalog(payload)
        entries = payload.get("entries", [])
        categories = payload.get("categories", [])
        report = {
            "ok": not errors,
            "catalog": str(catalog_path or CATALOG),
            "schema_version": payload.get("schema_version"),
            "updated_at": payload.get("updated_at"),
            "entries": len(entries) if isinstance(entries, list) else 0,
            "categories": len(categories) if isinstance(categories, list) else 0,
            "errors": errors,
        }
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif errors:
            for error in errors:
                print(f"- {error}")
            print(f"校验失败：{len(errors)} 项")
        else:
            print(f"校验通过：{report['entries']} 条条目 / {report['categories']} 个分类 / 0 项错误")
        return 0 if not errors else 1

    if not args.query.strip():
        print("错误：查询不能为空", file=sys.stderr)
        return 2
    if not 1 <= args.limit <= 5:
        print("错误：--limit 必须在 1-5 之间", file=sys.stderr)
        return 2
    try:
        result = search(payload, args.query.strip(), args.category, args.kind, args.limit)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_human(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
