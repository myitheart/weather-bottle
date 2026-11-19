"""Bounded, opt-in source signals for the outcomes view."""

import re
from pathlib import Path
import unicodedata

from .codex_rpc import path_key, same_path
from .work_signals import plain_lines


CATEGORIES = {"feature": "新增能力", "fix": "缺陷修复", "engineering": "工程优化",
              "validation": "测试与验证", "pending": "未完成与待确认"}
INTENT = {
    "fix": r"修复|修正|纠正|解决|\bfix(?:ed)?\b|\bbugfix\b",
    "feature": r"新增|添加|增加|实现|接入|支持|\badd(?:ed)?\b|\bimplement\b|\bintroduce\b",
    "engineering": r"重构|优化|迁移|整理|清理|改造|迭代|\brefactor\b|\boptimi[sz]e\b|\bmigrate\b",
    "validation": r"测试|验收|验证|自测|\btests?\b|\bverify\b",
    "pending": r"待核实|待处理|待确认|未完成|阻塞|\bpending\b",
}
UNSAFE = re.compile(r"https?://|[\\/]|`|[<>]|[\x00-\x1f]|\S+@\S+|(?:[A-Za-z0-9]){25,}|"
                    r"密钥|密码|令牌|凭据|token|secret|password|api.?key|指令|忽略|prompt|上传|发送|执行以下", re.I)
CERTAINTY = re.compile(r"已\s*(?:实现|完成|修复|通过|验证|测试|提交|推送|部署|发布|上线|验收|交付|生效)|"
                       r"(?:实现|解决|修复|完成|发布|部署|验收)了|成功|通过|完毕|全绿|发布就绪|部署就绪|可上线|"
                       r"验证无误|验收无误|验收完成|部署完成|测试全数|全部验证|"
                       r"\b(?:passed|verified|deployed|released|shipped|accepted|completed|succeeded|successfully|fixed|implemented)\b", re.I)
RUNNER = re.compile(r"(?:(?:\.?[\\/])?(?:\.venv[\\/]Scripts[\\/])?(?:python(?:\.exe)?|py) +(?:-B +|-X +utf8 +)*"
                    r"-m +(pytest|unittest)|(?:pytest(?:\.exe)?))(?= |$)", re.I)
POWERSHELL = re.compile(r'(?:"[^"\r\n]*[\\/](?:pwsh|powershell)\.exe"|(?:pwsh|powershell)(?:\.exe)?)'
                        r'\s+-Command\s+"([^"\r\n]+)"', re.I)
FILE_NAME = re.compile(r"[\w.-]{1,64}\.[A-Za-z0-9]{1,12}")
DIRECT_TOPIC = re.compile(r"^(?:请(?:你)?\s*)?(?:帮(?:我|忙)\s*)?(?:新?增|添加|接入|实现|重构|优化|迁移|修复|修正|"
                          r"解决|调整|补跑|完善|补充|待处理|待核实|fix\b|refactor\b|implement\b|add\b|"
                          r"update\b|improve\b|test\b)", re.I)


def classify(text):
    return next((kind for kind, pattern in INTENT.items() if re.search(pattern, text, re.I)), None)


def safe_excerpt(text):
    if (not isinstance(text, str) or not 3 <= len(text) <= 120 or
            any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in text)):
        return ""
    normalized = unicodedata.normalize("NFKC", text).strip()
    return normalized if 3 <= len(normalized) <= 120 and not UNSAFE.search(normalized) else ""


def actionable_topic(text):
    return (safe_excerpt(text) and DIRECT_TOPIC.search(text) and classify(text) and
            not CERTAINTY.search(text) and not re.search(r"\?|？|如果|是否|什么用|好不好", text))


def user_intent(content):
    if not isinstance(content, list):
        return ""
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        for line in plain_lines(part.get("text")):
            if actionable_topic(line):
                return line
    return ""


def test_result(item, cwd):
    command = item.get("command")
    if not same_path(item.get("cwd"), cwd) or not isinstance(command, str) or len(command) > 1000:
        return None
    command = command.strip()
    if shell := POWERSHELL.fullmatch(command):
        command = shell[1].strip()
        executable, space, arguments = command.partition(" ")
        command = executable.replace("\\\\", "\\") + space + arguments
    match = RUNNER.match(command)
    if (not match or re.search(r"[;&|<>`$\r\n]", command) or
            re.search(r"(?:^| )(?:--(?:collect-only|co|help|version)(?:=| |$)|-h(?: |$))", command)):
        return None
    runner = (match[1] or "pytest").lower()
    output = item.get("aggregatedOutput")
    if item.get("status") != "completed" or type(item.get("exitCode")) is not int or item["exitCode"] != 0:
        return {"runner": runner, "passed": 0}
    lines = output[-12000:].strip() if isinstance(output, str) else ""
    pattern = (r"(?m)^Ran ([1-9]\d{0,5}) tests? in [^\r\n]+\r?\n\s*OK\s*\Z" if runner == "unittest"
               else r"(?m)^(?:=+ *)?([1-9]\d{0,5}) passed in [\d.]+s *(?:=+)?\s*\Z")
    result = re.search(pattern, lines)
    return {"runner": runner, "passed": int(result[1]) if result else 0}


def project_changes(changes, cwd):
    """Retain only file counts and a few local file names for outcome descriptions."""
    root = Path(path_key(str(Path(cwd).resolve())))
    count, names = 0, []
    for change in changes:
        try:
            path = (Path(cwd) / change["path"]).resolve()
            normalized = Path(path_key(str(path)))
            if normalized == root or not normalized.is_relative_to(root):
                continue
        except (OSError, RuntimeError, ValueError):
            continue
        count += 1
        if len(names) < 8 and FILE_NAME.fullmatch(path.name) and path.name not in names:
            names.append(path.name)
    return count, names
