#!/usr/bin/env python3
"""Cross-platform NakamaDevs repository governance checks (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

CLI_VERSION = "1.3.0"
TYPES = "feat|fix|docs|refactor|test|build|ci|chore|perf|style|revert"
# Branch prefixes accept every commit type. "feature" stays as a legacy alias and
# must precede "feat" so the longer prefix matches first.
BRANCH_TYPES = f"feature|{TYPES}"
COMMIT_PATTERN = re.compile(rf"^({TYPES})(\([a-z0-9][a-z0-9-]*\))?!?: \S.*$")
EXACT_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[+-][A-Za-z0-9_.-]+)?$")
POSTGRES_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SKILLS_BUNDLE = "NakamaDevs/skills"
SKILLS_SOURCE = "https://github.com/NakamaDevs/skills.git"
GOVERNANCE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HARNESS_MINIMUM = (1, 9)
RUNNER_LABEL = re.compile(
    r"nakama-(?:dependabot-)?(?:linux-x64|macos-arm64|windows-arm64|windows-x64)"
    r"|nakama-untrusted-metadata-linux-x64"
)
PERSISTENT_RUNNERS = {
    "nakama-linux-x64",
    "nakama-macos-arm64",
    "nakama-windows-x64",
}
DEPENDABOT_RUNNERS = {
    "nakama-dependabot-linux-x64",
    "nakama-dependabot-macos-arm64",
    "nakama-dependabot-windows-x64",
}
RETIRED_RUNNERS = {
    "nakama-windows-arm64",
    "nakama-dependabot-windows-arm64",
}
WORKLOAD_RUNNERS = {
    "native-macos": {"nakama-macos-arm64"},
    "native-windows": {"nakama-windows-x64"},
    "server-only": {"nakama-linux-x64"},
    "cross-platform-desktop": {
        "nakama-linux-x64",
        "nakama-macos-arm64",
        "nakama-windows-x64",
    },
}


def fail(message: str, code: int = 1) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def exact_tool_version(name: str, value: object) -> bool:
    pattern = POSTGRES_VERSION if name == "postgres" else EXACT_VERSION
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], check=check, capture_output=True, text=True, encoding="utf-8"
    )


def repository_root() -> Path:
    result = run_git("rev-parse", "--show-toplevel", check=False)
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    return Path(__file__).resolve().parent.parent


def read_policy(root: Path) -> dict[str, str]:
    path = root / ".branch-policy"
    if not path.is_file():
        fail(f"Branch policy error: {path} is missing.")
    policy: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            policy[key.strip()] = value.strip()
    if not policy.get("LINEAR_TEAM_KEY") or not policy.get("LINEAR_PROJECT_NAME"):
        fail("Branch policy error: LINEAR_TEAM_KEY and LINEAR_PROJECT_NAME are required.")
    return policy


def validate_branch_format(branch: str, policy: dict[str, str]) -> str | None:
    if not branch:
        return "Branch policy error: detached HEAD is not allowed for commits."
    protected = {item.strip() for item in policy.get("PROTECTED_BRANCHES", "").split(",")}
    if branch in protected:
        return None
    team = re.escape(policy["LINEAR_TEAM_KEY"])
    # Bunko's user-authorized repository contract uses issue-only branch names.
    if policy.get("BRANCH_FORMAT") == "issue":
        plain = rf"^(?:{BRANCH_TYPES})/{team}-[1-9][0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*$"
        return None if re.fullmatch(plain, branch) else f"Invalid branch name: {branch}"
    human = rf"^(?:{BRANCH_TYPES})/[a-z0-9]+(?:-[a-z0-9]+)*-{team}-[1-9][0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*$"
    agent = rf"^(?:{BRANCH_TYPES})/cx/{team}-[1-9][0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*$"
    if re.fullmatch(rf"(?:{human})|(?:{agent})", branch):
        return None
    return f"Invalid branch name: {branch}"


def linear_issue(branch: str, policy: dict[str, str], api_key: str, api_url: str) -> None:
    ticket_match = re.search(rf"{re.escape(policy['LINEAR_TEAM_KEY'])}-[1-9][0-9]*", branch)
    if not ticket_match:
        fail("Branch policy error: could not extract the Linear issue identifier.")
    ticket = ticket_match.group(0)
    payload = json.dumps(
        {
            "query": "query BranchIssue($id: String!) { issue(id: $id) { identifier project { name } team { key } } }",
            "variables": {"id": ticket},
        }
    ).encode()
    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        fail(f"Could not verify {ticket} with Linear: {error}")
    issue = ((result.get("data") or {}).get("issue") or {})
    if issue.get("identifier") != ticket:
        fail(f"Linear issue {ticket} does not exist or is not accessible.")
    if (issue.get("team") or {}).get("key") != policy["LINEAR_TEAM_KEY"] or (
        issue.get("project") or {}
    ).get("name") != policy["LINEAR_PROJECT_NAME"]:
        fail(
            f"Linear issue {ticket} must belong to team {policy['LINEAR_TEAM_KEY']} "
            f"and project {policy['LINEAR_PROJECT_NAME']}."
        )
    print(f"Branch policy verified: {branch} references {ticket} in {policy['LINEAR_PROJECT_NAME']}.")


def command_branch(args: argparse.Namespace) -> None:
    root = repository_root()
    policy = read_policy(root)
    branch = args.branch
    if branch is None:
        branch = run_git("branch", "--show-current").stdout.strip()
    error = validate_branch_format(branch, policy)
    if error:
        team = policy["LINEAR_TEAM_KEY"]
        print(error, file=sys.stderr)
        print(
            (f"Use <type>/{team}-123-description." if policy.get("BRANCH_FORMAT") == "issue" else
             f"Use <type>/username-{team}-123-description or <type>/cx/{team}-123-description."),
            f"Types: {BRANCH_TYPES.replace('|', ', ')}.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if args.format_only or branch in {
        item.strip() for item in policy.get("PROTECTED_BRANCHES", "").split(",")
    }:
        return
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        fail(
            "Cannot verify the Linear issue because LINEAR_API_KEY is not set. "
            f"Create or move it into the {policy['LINEAR_PROJECT_NAME']} project and retry."
        )
    linear_issue(
        branch,
        policy,
        api_key,
        os.environ.get("LINEAR_API_URL", "https://api.linear.app/graphql"),
    )


def validate_commit_header(header: str) -> str | None:
    if len(header) > 100:
        return "Invalid commit message: the header must be at most 100 characters."
    if not COMMIT_PATTERN.fullmatch(header):
        return "Invalid commit message. Use Conventional Commits: type(optional-scope)!: description"
    return None


def command_commit(args: argparse.Namespace) -> None:
    path = Path(args.message_file)
    if not path.is_file():
        fail("Usage: nakama_governance.py commit <commit-message-file>", 2)
    header = path.read_text(encoding="utf-8-sig").splitlines()[0].rstrip("\r")
    error = validate_commit_header(header)
    if error:
        fail(error)


def command_pr_branch(_: argparse.Namespace) -> None:
    head = os.environ.get("PR_HEAD_BRANCH", "")
    base = os.environ.get("PR_BASE_REVISION", "")
    if not head:
        print("PR branch policy skipped outside a pull_request event.")
        return
    if not base:
        fail("PR branch policy error: base commit unavailable; checkout with fetch-depth 2 or greater.")
    result = run_git("ls-tree", "--name-only", base, "--", ".branch-policy", check=False)
    if result.returncode != 0:
        fail("PR branch policy error: base commit unavailable; checkout with fetch-depth 2 or greater.")
    if result.stdout.strip() != ".branch-policy":
        print("PR branch policy bootstrap: the base predates .branch-policy; enforcement begins after merge.")
        return
    # NAK-1009: CI supplies the PR author directly from GitHub's event context.
    # A branch prefix alone must never grant the Dependabot exception.
    if os.environ.get("PR_AUTHOR_LOGIN") == "dependabot[bot]":
        if not re.fullmatch(
            r"dependabot/[a-z][a-z0-9_-]*/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", head
        ):
            fail(f"Invalid Dependabot branch name: {head}")
        print(f"PR branch policy verified: Dependabot branch {head}.")
        return
    error = validate_branch_format(head, read_policy(repository_root()))
    if error:
        fail(error)


def command_pr_title(_: argparse.Namespace) -> None:
    title = os.environ.get("PR_TITLE", "")
    if not title:
        print("PR title policy skipped outside a pull_request event.")
        return
    error = validate_commit_header(title)
    if error:
        fail(error)
    print(f"PR title policy verified: {title}")


def load_context(root: Path) -> dict[str, object]:
    path = root / ".nakama" / "repository.toml"
    if not path.is_file():
        fail(f"agent contract: missing {path.relative_to(root)}")
    with path.open("rb") as stream:
        return tomllib.load(stream)


def validate_external_skills_reference(skills: dict[str, object]) -> str | None:
    if skills.get("bundle") != SKILLS_BUNDLE:
        return f"agent contract: skills.bundle must be {SKILLS_BUNDLE}"
    if skills.get("source") != SKILLS_SOURCE:
        return f"agent contract: skills.source must be {SKILLS_SOURCE}"
    version = skills.get("version")
    if not exact_tool_version("skills", version):
        return "agent contract: skills.version must be an exact semantic version"
    revision = skills.get("revision")
    if not isinstance(revision, str) or not FULL_SHA.fullmatch(revision):
        return "agent contract: skills revision must be an exact 40-character commit SHA"
    if revision == "0" * 40:
        return "agent contract: skills revision must identify a catalog commit"
    return None


def governance_release(version: object) -> tuple[int, int] | None:
    if not isinstance(version, str) or not GOVERNANCE_VERSION.fullmatch(version):
        return None
    major, minor = version.split(".")[:2]
    return int(major), int(minor)


def validate_harness_declaration(context: dict[str, object]) -> str | None:
    minimum = ".".join(str(part) for part in HARNESS_MINIMUM)
    release = governance_release(context.get("governance_version"))
    if release is None:
        return (
            "agent contract: governance_version must be an exact release version "
            "without prerelease or build metadata"
        )
    harness = context.get("harness")
    if harness is None:
        if release < HARNESS_MINIMUM:
            return None
        return f"agent contract: governance {minimum} profiles must declare [harness]"
    if not isinstance(harness, dict):
        return "agent contract: [harness] must be a table"
    if "agent_ready" not in harness:
        return "agent contract: missing harness.agent_ready"
    ready = harness["agent_ready"]
    if not isinstance(ready, bool):
        return "agent contract: harness.agent_ready must be true or false"
    if ready and release < HARNESS_MINIMUM:
        return f"agent contract: harness.agent_ready requires governance {minimum} or later"
    return None


def command_agent(_: argparse.Namespace) -> None:
    root = repository_root()
    context = load_context(root)
    required_top = ("schema_version", "repository", "kind", "governance_version")
    required_sections = {
        "skills": ("bundle", "version", "source", "revision"),
        "linear": ("team", "project"),
        "quality": ("quick", "full", "hooks_install"),
        "review": ("router",),
        "discord": ("guild_id", "project_thread_id", "operations_channel_id", "operator_role_id"),
    }
    for key in required_top:
        if key not in context:
            fail(f"agent contract: missing {key}")
    for section, keys in required_sections.items():
        values = context.get(section)
        if not isinstance(values, dict):
            fail(f"agent contract: missing [{section}]")
        for key in keys:
            if key not in values:
                fail(f"agent contract: missing {section}.{key}")
    skills = context["skills"]
    assert isinstance(skills, dict)
    revision = str(skills["revision"])
    version = str(skills["version"])
    if revision == "self":
        if not (root / "skills").is_dir():
            fail("agent contract: self-hosted skills require the local skills directory")
    else:
        error = validate_external_skills_reference(skills)
        if error:
            fail(error)
    error = validate_harness_declaration(context)
    if error:
        fail(error)
    harness = context.get("harness")
    ready = isinstance(harness, dict) and harness.get("agent_ready") is True
    print(f"agent contract: valid ({version} at {revision}; agent_ready={str(ready).lower()})")


def command_secrets(args: argparse.Namespace) -> None:
    root = repository_root()
    gitleaks = shutil.which("gitleaks")
    if not gitleaks:
        fail("gitleaks is required; install the repository's pinned mise tools.", 2)
    config = str(root / ".gitleaks.toml")
    canary = "NAKAMA_SECRET_SCAN_" + "CANARY_7M4Q9Z2K8R5T1V6X3C0B7N4P9L2D8F5H"
    canary_result = subprocess.run(
        [gitleaks, "stdin", "--config", config, "--redact=100", "--no-banner"],
        input=canary,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if canary_result.returncode != 1:
        fail(f"Secret-scanner canary failed; expected a finding, got exit {canary_result.returncode}.")
    command = [gitleaks, "git"]
    if args.mode == "staged":
        command.append("--staged")
    command.extend(["--config", config, "--redact=100", "--no-banner", str(root)])
    raise SystemExit(subprocess.run(command, check=False).returncode)


def workflow_files(root: Path) -> list[Path]:
    directory = root / ".github" / "workflows"
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]) if directory.is_dir() else []


def workflow_job_blocks(text: str) -> list[tuple[str, str]]:
    """Return top-level workflow job blocks without requiring a YAML dependency."""
    jobs: list[tuple[str, str]] = []
    current_name: str | None = None
    current_lines: list[str] = []
    in_jobs = False
    for line in text.splitlines():
        if re.fullmatch(r"jobs:\s*(?:#.*)?", line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line and not line[0].isspace():
            break
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$", line)
        if match:
            if current_name is not None:
                jobs.append((current_name, "\n".join(current_lines)))
            current_name = match.group(1)
            current_lines = [line]
        elif current_name is not None:
            current_lines.append(line)
    if current_name is not None:
        jobs.append((current_name, "\n".join(current_lines)))
    return jobs


def workflow_job_field(block: str, field: str) -> str:
    lines = block.splitlines()
    for index, line in enumerate(lines):
        match = re.match(rf"^    {re.escape(field)}:\s*(.*)$", line)
        if not match:
            continue
        values = [match.group(1)]
        for continuation in lines[index + 1 :]:
            if continuation.strip() and len(continuation) - len(continuation.lstrip()) <= 4:
                break
            values.append(continuation.strip())
        return " ".join(values)
    return ""


def workflow_uses_pull_requests(text: str) -> bool:
    return re.search(r"^  pull_request(?:_target)?\s*:", text, re.MULTILINE) is not None


def workflow_event_errors(path: str, text: str) -> list[str]:
    if re.search(r"\bready_for_review\b", text):
        return [
            f"{path}: ready_for_review duplicates checks already run for the current commit."
        ]
    return []


def command_workflow_events(_: argparse.Namespace) -> None:
    root = repository_root()
    errors: list[str] = []
    for path in workflow_files(root):
        errors.extend(workflow_event_errors(str(path.relative_to(root)), path.read_text(encoding="utf-8")))
    if errors:
        fail("\n".join(errors))
    print("Workflow event policy checks passed.")


def runner_policy_errors(path: str, text: str) -> list[str]:
    errors: list[str] = []
    cross_platform_labels: set[str] = set()
    pull_requests = workflow_uses_pull_requests(text)
    if pull_requests and re.search(r"github\.(?:triggering_)?actor(?:_id)?\b", text):
        errors.append(
            f"{path}: pull-request routing must classify github.event.pull_request.user.login, "
            "not github.actor or github.triggering_actor."
        )

    author_selector = re.compile(
        r"github\.event\.pull_request\.user\.login\s*==\s*['\"]dependabot\[bot\]['\"]"
    )
    fork_guard = re.compile(
        r"github\.event\.pull_request\.head\.repo\.full_name\s*==\s*github\.repository"
    )
    for job, block in workflow_job_blocks(text):
        runs_on = workflow_job_field(block, "runs-on")
        if not runs_on:
            continue
        labels = set(RUNNER_LABEL.findall(runs_on))
        persistent = labels & PERSISTENT_RUNNERS
        dependabot = labels & DEPENDABOT_RUNNERS
        location = f"{path}: job {job}"
        retired = labels & RETIRED_RUNNERS
        if retired:
            errors.append(
                f"{location}: retired Windows ARM64 runner labels are forbidden: "
                f"{', '.join(sorted(retired))}; active Windows CI uses x64 only."
            )
        workload_matches = re.findall(r"#\s*nakama-workload:\s*([a-z0-9-]+)", block)
        workload = workload_matches[0] if len(workload_matches) == 1 else ""

        if persistent and len(workload_matches) != 1:
            errors.append(
                f"{location}: persistent execution requires exactly one "
                "'# nakama-workload: <class>' declaration."
            )
        elif persistent and workload not in WORKLOAD_RUNNERS:
            errors.append(f"{location}: unknown workload class {workload!r}.")
        elif persistent:
            expected = WORKLOAD_RUNNERS[workload]
            if workload == "cross-platform-desktop":
                if not persistent <= expected:
                    errors.append(
                        f"{location}: cross-platform desktop jobs may use only "
                        "nakama-macos-arm64, nakama-linux-x64, and nakama-windows-x64."
                    )
                cross_platform_labels.update(persistent & expected)
            elif persistent != expected:
                errors.append(
                    f"{location}: workload {workload} requires {', '.join(sorted(expected))}."
                )

        if labels & {"nakama-windows-x64", "nakama-dependabot-windows-x64"} and (
            "uses: jdx/mise-action@" in block
        ):
            setup_index = block.find("- name: Configure Windows runner tools")
            mise_index = block.find("- uses: jdx/mise-action@")
            if setup_index < 0 or setup_index > mise_index:
                errors.append(
                    f"{location}: configure Windows runner tools before jdx/mise-action."
                )
            portability_markers = (
                "shell: pwsh",
                r"Git\usr\bin",
                "unzip.exe",
                "$env:GITHUB_PATH",
                "MISE_DATA_DIR=$(Join-Path $env:RUNNER_TOOL_CACHE 'mise-data')",
                "MISE_CACHE_DIR=$(Join-Path $env:RUNNER_TOOL_CACHE 'mise-cache')",
            )
            missing = [marker for marker in portability_markers if marker not in block]
            if missing:
                errors.append(
                    f"{location}: Windows mise portability setup is missing: {', '.join(missing)}."
                )

        if "nakama-untrusted-metadata-linux-x64" in labels:
            if labels != {"nakama-untrusted-metadata-linux-x64"}:
                errors.append(
                    f"{location}: metadata-only jobs must select only "
                    "nakama-untrusted-metadata-linux-x64."
                )
            if workload_matches != ["metadata-only"]:
                errors.append(
                    f"{location}: the untrusted metadata lane requires "
                    "'# nakama-workload: metadata-only'."
                )
            forbidden_metadata = (
                r"uses:\s*actions/checkout@",
                r"uses:\s*\./",
                r"(?:^|\s)mise\s+",
                r"(?:^|\s)(?:python\s+)?scripts[/\\]",
            )
            if any(re.search(pattern, block) for pattern in forbidden_metadata):
                errors.append(
                    f"{location}: metadata-only jobs must not check out or execute repository code."
                )

        if dependabot:
            if not pull_requests or not author_selector.search(runs_on):
                errors.append(
                    f"{location}: Dependabot runner selection must use "
                    "github.event.pull_request.user.login == 'dependabot[bot]' in runs-on."
                )
            if re.search(r"\b(?:inputs|matrix|vars)\.", runs_on):
                errors.append(
                    f"{location}: Dependabot routing may not use configurable or capacity-based fallback."
                )

        if pull_requests and persistent:
            condition = workflow_job_field(block, "if")
            if not fork_guard.search(condition):
                errors.append(
                    f"{location}: persistent PR execution must reject forks before runner assignment."
                )
            for label in sorted(persistent):
                expected = label.replace("nakama-", "nakama-dependabot-", 1)
                safe_pair = re.compile(
                    author_selector.pattern
                    + rf"\s*&&\s*['\"]{re.escape(expected)}['\"]"
                    + rf"\s*\|\|\s*['\"]{re.escape(label)}['\"]"
                )
                if expected not in dependabot or not safe_pair.search(runs_on):
                    errors.append(
                        f"{location}: route pull_request.user.login == 'dependabot[bot]' "
                        f"directly to {expected}, then {label}; reversed, mismatched-platform, or "
                        "configurable fallback is forbidden."
                    )
            for label in sorted(dependabot):
                expected = label.replace("nakama-dependabot-", "nakama-", 1)
                if expected not in persistent:
                    errors.append(
                        f"{location}: {label} must pair with {expected} for non-Dependabot events."
                    )
    if cross_platform_labels and cross_platform_labels != WORKLOAD_RUNNERS["cross-platform-desktop"]:
        missing = WORKLOAD_RUNNERS["cross-platform-desktop"] - cross_platform_labels
        errors.append(
            f"{path}: cross-platform desktop coverage is missing: {', '.join(sorted(missing))}."
        )
    return errors


# NAK-1009: owner-approved Bunko exception; pinned Kaicho mirrors stay unchanged.
BUNKO_PUBLIC_CI_GUARD = (
    "${{ github.event.repository.visibility == 'public' && "
    "(github.event_name != 'pull_request' || "
    "github.event.pull_request.head.repo.full_name == github.repository) }}"
)


def bunko_public_ci_errors(path: str, text: str) -> list[str]:
    """Allow only Bunko's reviewed public CI job, never configurable runners."""
    errors: list[str] = []
    jobs = workflow_job_blocks(text)
    # Keep the accepted YAML layout explicit: the stdlib job reader does not
    # resolve flow mappings, aliases, or alternative indentation.
    job_section = text.split("\njobs:\n", 1)[-1]
    for line in job_section.splitlines():
        if re.match(r"^  \S", line) and not re.fullmatch(
            r"  [A-Za-z0-9_-]+:\s*(?:#.*)?", line
        ) and not line.lstrip().startswith("#"):
            errors.append(f"{path}: Bunko CI requires explicit two-space job blocks.")
    if not jobs:
        return [f"{path}: Bunko public CI requires explicit job blocks."]
    for job, block in jobs:
        location = f"{path}: job {job}"
        if (path, job) != (".github/workflows/ci.yml", "verify"):
            errors.append(f"{location}: outside the NAK-1009 public CI exception.")
        # Exact values deliberately reject larger runners, groups, matrices,
        # expressions, reusable workflows, and weakened or commented guards.
        if workflow_job_field(block, "runs-on").strip() != "ubuntu-24.04":
            errors.append(f"{location}: Bunko permits only the standard ubuntu-24.04 runner.")
        if workflow_job_field(block, "if").strip() != BUNKO_PUBLIC_CI_GUARD:
            errors.append(f"{location}: require the public-repository and same-repository PR guard.")
        if re.findall(r"#\s*nakama-workload:\s*([a-z0-9-]+)", block) != ["server-only"]:
            errors.append(f"{location}: Bunko CI requires the server-only workload.")
        if workflow_job_field(block, "uses"):
            errors.append(f"{location}: reusable workflows are outside the NAK-1009 exception.")
    return errors


def command_runner_policy(_: argparse.Namespace) -> None:
    root = repository_root()
    errors: list[str] = []
    bunko = load_context(root).get("repository") == "NakamaDevs/Bunko"
    for path in workflow_files(root):
        relative_path = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8")
        errors.extend(runner_policy_errors(relative_path, text))
        if bunko:
            errors.extend(bunko_public_ci_errors(relative_path, text))
    if errors:
        fail("\n".join(errors))
    print("Runner routing policy checks passed.")


def command_supply_chain(_: argparse.Namespace) -> None:
    root = repository_root()
    errors: list[str] = []
    dependabot = root / ".github" / "dependabot.yml"
    if not dependabot.is_file():
        errors.append("Missing .github/dependabot.yml.")
    else:
        text = dependabot.read_text(encoding="utf-8")
        ecosystems = len(re.findall(r"^\s{2}- package-ecosystem:", text, re.MULTILINE))
        cooldowns = len(re.findall(r"^\s{6}default-days:\s*7(?:\s|$)", text, re.MULTILINE))
        if ecosystems == 0 or ecosystems != cooldowns:
            errors.append("Every Dependabot ecosystem must set cooldown.default-days to 7.")
    workflows = workflow_files(root)
    workflow_text = "\n".join(path.read_text(encoding="utf-8") for path in workflows)
    for match in re.finditer(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s]+)", workflow_text, re.MULTILINE):
        reference = match.group(1)
        if reference.startswith("./") or reference.startswith("docker://"):
            continue
        revision = reference.rsplit("@", 1)[-1]
        if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
            errors.append(f"External GitHub Action is not pinned to a full commit SHA: {reference}")
    if "jdx/mise-action@" in workflow_text and not re.search(
        r"MISE_LOCKED:\s*['\"]?1['\"]?", workflow_text
    ):
        errors.append("Workflows using mise-action must set MISE_LOCKED=1.")
    mise_path = root / "mise.toml"
    if mise_path.is_file():
        if not (root / "mise.lock").is_file():
            errors.append("mise.toml requires a committed mise.lock.")
        with mise_path.open("rb") as stream:
            tools = tomllib.load(stream).get("tools", {})
        for name, value in tools.items():
            if not exact_tool_version(name, value):
                errors.append(f"Non-exact mise tool version: {name} = {value!r}")
    if not (root / ".gitleaks.toml").is_file():
        errors.append("Missing .gitleaks.toml.")
    source = Path(__file__).read_text(encoding="utf-8")
    if "--redact=100" not in source:
        errors.append("Secret-scanner output must be fully redacted.")
    if not re.search(r'^\s*gitleaks\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"\s*$', mise_path.read_text(encoding="utf-8"), re.MULTILINE):
        errors.append("Gitleaks must be pinned to an exact version in mise.toml.")
    if 'id = "nakama-secret-scan-canary"' not in (root / ".gitleaks.toml").read_text(encoding="utf-8"):
        errors.append("The Gitleaks configuration must retain the detector canary rule.")
    if workflows and not re.search(r"mise run (security:secrets|verify|validate)", workflow_text):
        errors.append("CI must run secret history scanning directly or through its aggregate.")
    if errors:
        fail("\n".join(errors))
    print("Supply-chain policy checks passed.")


def command_self_test(_: argparse.Namespace) -> None:
    policy = read_policy(repository_root())
    if policy.get("BRANCH_FORMAT") == "issue":
        assert validate_branch_format("feat/NAK-913-versioned-workspace", policy) is None
        assert validate_branch_format("feat/cx/NAK-913-versioned-workspace", policy) is not None
        assert validate_branch_format("feat/user-NAK-913-versioned-workspace", policy) is not None
        policy = {key: value for key, value in policy.items() if key != "BRANCH_FORMAT"}
    passing = (
        "feature/hectorddmx-NAK-5-branch-governance",
        "fix/hector-dd-NAK-5-branch-governance",
        "feature/cx/NAK-5-branch-governance",
        "fix/cx/NAK-5-branch-governance",
        "feat/cx/NAK-5-branch-governance",
        "docs/cx/NAK-5-branch-governance",
        "chore/hectorddmx-NAK-5-branch-governance",
        "revert/cx/NAK-5-branch-governance",
        "main",
    )
    failing = (
        "feature/NAK-5-branch-governance",
        "fix/cx/hectorddmx-NAK-5-branch-governance",
        "feature/cx/missing-ticket",
        "chores/hectorddmx-NAK-5-branch-governance",
        "release/cx/NAK-5-branch-governance",
        "fix/cx/nak-5-branch-governance",
    )
    if any(validate_branch_format(value, policy) for value in passing):
        fail("Self-test failed: a valid branch was rejected.")
    if any(validate_branch_format(value, policy) is None for value in failing):
        fail("Self-test failed: an invalid branch was accepted.")
    valid_messages = (
        "feat: add branch policy",
        "fix(hooks): reject missing Linear issues",
        "feat(api)!: remove legacy response fields",
        "docs: explain semantic commits",
    )
    invalid_messages = ("added branch policy", "feature: add branch policy", "FEAT: add branch policy", "fix: ")
    if any(validate_commit_header(value) for value in valid_messages):
        fail("Self-test failed: a valid commit header was rejected.")
    if any(validate_commit_header(value) is None for value in invalid_messages):
        fail("Self-test failed: an invalid commit header was accepted.")
    safe_event_workflow = """on:
  pull_request:
    types: [opened, synchronize, reopened]
"""
    unsafe_event_workflow = safe_event_workflow.replace(
        "reopened]", "reopened, ready_for_review]"
    )
    if workflow_event_errors("safe-events.yml", safe_event_workflow):
        fail("Self-test failed: safe pull-request events were rejected.")
    if not workflow_event_errors("unsafe-events.yml", unsafe_event_workflow):
        fail("Self-test failed: duplicate ready-for-review event was accepted.")
    safe_runner_workflow = """on:
  pull_request:
jobs:
  verify:
    if: ${{ github.event.pull_request.head.repo.full_name == github.repository }}
    # nakama-workload: native-windows
    runs-on: ${{ github.event.pull_request.user.login == 'dependabot[bot]' && 'nakama-dependabot-windows-x64' || 'nakama-windows-x64' }}
"""
    safe_macos_workflow = safe_runner_workflow.replace(
        "native-windows", "native-macos"
    ).replace("windows-x64", "macos-arm64")
    safe_server_workflow = safe_runner_workflow.replace(
        "native-windows", "server-only"
    ).replace("windows-x64", "linux-x64")
    safe_metadata_workflow = """on:
  pull_request:
jobs:
  gate:
    # nakama-workload: metadata-only
    runs-on: nakama-untrusted-metadata-linux-x64
    steps:
      - run: echo metadata-only
"""
    safe_cross_platform_workflow = """on:
  pull_request:
jobs:
  macos:
    if: ${{ github.event.pull_request.head.repo.full_name == github.repository }}
    # nakama-workload: cross-platform-desktop
    runs-on: ${{ github.event.pull_request.user.login == 'dependabot[bot]' && 'nakama-dependabot-macos-arm64' || 'nakama-macos-arm64' }}
  linux:
    if: ${{ github.event.pull_request.head.repo.full_name == github.repository }}
    # nakama-workload: cross-platform-desktop
    runs-on: ${{ github.event.pull_request.user.login == 'dependabot[bot]' && 'nakama-dependabot-linux-x64' || 'nakama-linux-x64' }}
  windows:
    if: ${{ github.event.pull_request.head.repo.full_name == github.repository }}
    # nakama-workload: cross-platform-desktop
    runs-on: ${{ github.event.pull_request.user.login == 'dependabot[bot]' && 'nakama-dependabot-windows-x64' || 'nakama-windows-x64' }}
"""
    windows_setup = """      - name: Configure Windows runner tools
        shell: pwsh
        run: |
          $gitTools = Join-Path $env:ProgramFiles "Git\\usr\\bin"
          if (-not (Test-Path (Join-Path $gitTools "unzip.exe"))) { throw "missing" }
          Add-Content -Path $env:GITHUB_PATH -Value $gitTools
          Add-Content -Path $env:GITHUB_ENV -Value "MISE_DATA_DIR=$(Join-Path $env:RUNNER_TOOL_CACHE 'mise-data')"
          Add-Content -Path $env:GITHUB_ENV -Value "MISE_CACHE_DIR=$(Join-Path $env:RUNNER_TOOL_CACHE 'mise-cache')"
"""
    windows_mise = "      - uses: jdx/mise-action@7e36c90d9ab29c415a2384db3006f3ec8a8cc654"
    safe_windows_mise_workflow = safe_runner_workflow + "    steps:\n" + windows_setup + windows_mise
    unsafe_runner_workflows = (
        safe_runner_workflow.replace("github.event.pull_request.user.login", "github.actor"),
        safe_runner_workflow.replace(
            "${{ github.event.pull_request.user.login == 'dependabot[bot]' && "
            "'nakama-dependabot-windows-x64' || 'nakama-windows-x64' }}",
            "nakama-windows-x64",
        ),
        safe_runner_workflow.replace("nakama-dependabot-windows-x64", "nakama-dependabot-linux-x64"),
        safe_runner_workflow.replace(
            "'nakama-dependabot-windows-x64' || 'nakama-windows-x64'",
            "'nakama-windows-x64' || 'nakama-dependabot-windows-x64'",
        ),
        safe_runner_workflow.replace(
            "'nakama-windows-x64' }}", "vars.CI_RUNNER }}"
        ),
        safe_macos_workflow.replace("    # nakama-workload: native-macos\n", ""),
        safe_runner_workflow.replace("native-windows", "server-only"),
        safe_runner_workflow.replace("windows-x64", "windows-arm64"),
        safe_cross_platform_workflow.replace(
            "  linux:\n    if: ${{ github.event.pull_request.head.repo.full_name == github.repository }}\n"
            "    # nakama-workload: cross-platform-desktop\n"
            "    runs-on: ${{ github.event.pull_request.user.login == 'dependabot[bot]' && "
            "'nakama-dependabot-linux-x64' || 'nakama-linux-x64' }}\n",
            "",
        ),
        safe_windows_mise_workflow.replace("$env:GITHUB_PATH", "$env:PATH"),
        safe_windows_mise_workflow.replace(
            windows_setup + windows_mise, windows_mise + "\n" + windows_setup
        ),
        """on:
  pull_request:
jobs:
  gate:
    runs-on: ${{ github.event_name == 'pull_request' && 'nakama-dependabot-linux-x64' || 'nakama-linux-x64' }}
""",
        """on:
  pull_request:
jobs:
  gate:
    # nakama-workload: metadata-only
    runs-on: nakama-untrusted-metadata-linux-x64
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
""",
        safe_metadata_workflow.replace("echo metadata-only", "python scripts/check.py"),
        safe_metadata_workflow.replace("- run: echo metadata-only", "- uses: ./actions/check"),
        safe_metadata_workflow.replace(
            "runs-on: nakama-untrusted-metadata-linux-x64",
            "runs-on: [nakama-untrusted-metadata-linux-x64, nakama-dependabot-linux-x64]",
        ),
    )
    if runner_policy_errors("safe.yml", safe_runner_workflow):
        fail("Self-test failed: safe Windows x64 runner routing was rejected.")
    if runner_policy_errors("safe-macos.yml", safe_macos_workflow):
        fail("Self-test failed: a native macOS lane was rejected.")
    if runner_policy_errors("safe-server.yml", safe_server_workflow):
        fail("Self-test failed: a server-only Linux lane was rejected.")
    if runner_policy_errors("safe-metadata.yml", safe_metadata_workflow):
        fail("Self-test failed: a metadata-only disposable lane was rejected.")
    if runner_policy_errors("safe-cross-platform.yml", safe_cross_platform_workflow):
        fail("Self-test failed: complete cross-platform desktop coverage was rejected.")
    if runner_policy_errors("safe-windows-mise.yml", safe_windows_mise_workflow):
        fail("Self-test failed: safe Windows mise portability setup was rejected.")
    if any(not runner_policy_errors("unsafe.yml", value) for value in unsafe_runner_workflows):
        fail("Self-test failed: unsafe runner routing was accepted.")
    exact_versions = (
        ("postgres", "17.10", True),
        ("postgres", "17", False),
        ("postgres", "17.10.1", False),
        ("python", "3.14.6", True),
        ("python", "3.14", False),
        ("gitleaks", "8.30.0", True),
        ("actionlint", "1.7", False),
        ("python", 3.146, False),
    )
    for tool, tool_version, expected in exact_versions:
        if exact_tool_version(tool, tool_version) is not expected:
            fail(f"Self-test failed: {tool} version {tool_version!r} exactness is invalid.")
    valid_harness = (
        {"governance_version": "1.9.0", "harness": {"agent_ready": False}},
        {"governance_version": "1.9.0", "harness": {"agent_ready": True}},
        {"governance_version": "1.10.0", "harness": {"agent_ready": False}},
        {"governance_version": "2.0.0", "harness": {"agent_ready": True}},
        {"governance_version": "1.8.0"},
        {"governance_version": "1.7.3"},
        {"governance_version": "1.8.0", "harness": {"agent_ready": False}},
    )
    invalid_harness = (
        {"governance_version": "1.9.0"},
        {"governance_version": "1.9.0", "harness": {}},
        {"governance_version": "1.9.0", "harness": {"agent_ready": "false"}},
        {"governance_version": "1.9.0", "harness": {"agent_ready": None}},
        {"governance_version": "1.9.0", "harness": "yes"},
        {"governance_version": "1.8.0", "harness": {"agent_ready": "true"}},
        {"governance_version": "1.8.0", "harness": {"agent_ready": True}},
        {"governance_version": "1.0.0", "harness": {"agent_ready": True}},
        {"governance_version": "1.9.0-rc.1", "harness": {"agent_ready": False}},
        {"governance_version": "1.9.0+build.5", "harness": {"agent_ready": True}},
        {"governance_version": "1.8.0-rc.1"},
        {"governance_version": "2.0.0-alpha", "harness": {"agent_ready": False}},
        {"governance_version": "1.9"},
        {},
    )
    if any(validate_harness_declaration(value) for value in valid_harness):
        fail("Self-test failed: a valid harness declaration was rejected.")
    if any(validate_harness_declaration(value) is None for value in invalid_harness):
        fail("Self-test failed: an invalid harness declaration was accepted.")
    command_agent(argparse.Namespace())
    command_supply_chain(argparse.Namespace())
    command_runner_policy(argparse.Namespace())
    command_workflow_events(argparse.Namespace())
    print(f"Governance CLI {CLI_VERSION} self-tests passed.")


def command_install_hooks(_: argparse.Namespace) -> None:
    prek = shutil.which("prek")
    if not prek:
        fail("prek is required; install the repository's pinned mise tools.", 2)
    run_git("config", "--unset-all", "core.hooksPath", check=False)
    command = [
        prek,
        "install",
        "--hook-type",
        "pre-commit",
        "--hook-type",
        "pre-push",
        "--hook-type",
        "commit-msg",
        "--prepare-hooks",
    ]
    raise SystemExit(subprocess.run(command, check=False).returncode)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--version", action="version", version=CLI_VERSION)
    commands = result.add_subparsers(dest="command", required=True)
    branch = commands.add_parser("branch", help="validate a branch and optionally its Linear issue")
    branch.add_argument("--format-only", action="store_true")
    branch.add_argument("branch", nargs="?")
    branch.set_defaults(handler=command_branch)
    commit = commands.add_parser("commit", help="validate a Conventional Commit message file")
    commit.add_argument("message_file")
    commit.set_defaults(handler=command_commit)
    commands.add_parser("pr-branch", help="validate PR_HEAD_BRANCH").set_defaults(handler=command_pr_branch)
    commands.add_parser("pr-title", help="validate PR_TITLE").set_defaults(handler=command_pr_title)
    commands.add_parser("agent-contract", help="validate plugin and repository context").set_defaults(handler=command_agent)
    secrets = commands.add_parser("secrets", help="run the pinned secret scanner")
    secrets.add_argument("mode", choices=("history", "staged"), nargs="?", default="history")
    secrets.set_defaults(handler=command_secrets)
    commands.add_parser("supply-chain", help="validate immutable dependency controls").set_defaults(handler=command_supply_chain)
    commands.add_parser("runner-policy", help="validate workflow runner trust routing").set_defaults(handler=command_runner_policy)
    commands.add_parser("workflow-events", help="reject duplicate pull-request activity triggers").set_defaults(handler=command_workflow_events)
    commands.add_parser("self-test", help="run portable governance regression tests").set_defaults(handler=command_self_test)
    commands.add_parser("install-hooks", help="install cross-platform prek Git hooks").set_defaults(handler=command_install_hooks)
    return result


def main() -> None:
    args = parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
