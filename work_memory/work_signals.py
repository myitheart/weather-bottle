"""Extract a small set of explicit work signals without retaining message text."""

import re
from urllib.parse import urlsplit


MILESTONES = {
    "implementation": "实现", "test": "本地测试", "commit": "Git 提交",
    "push": "Git 推送", "beta": "Beta 部署", "acceptance": "验收",
}
OUTCOMES = {"success": "成功", "failed": "失败", "pending": "待处理", "unknown": "未知", "conflict": "有冲突"}
HEADER = re.compile(r"(?:事项(?:标识)?|工单(?:编号)?|Issue|Work item)\s*[:：]\s*(\S+)", re.I)
TICKET = re.compile(r"[A-Z][A-Z0-9]{1,19}-[1-9][0-9]{0,9}")
REPO_ISSUE = re.compile(r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+/(?:issues|pull|-/issues|-/merge_requests)/[1-9][0-9]{0,9}")
BROWSE = re.compile(r"/browse/([A-Z][A-Z0-9]{1,19}-[1-9][0-9]{0,9})")
CLAIMS = {
    "已完成修改": ("implementation", "success"),
    "本地测试通过": ("test", "success"), "本地测试失败": ("test", "failed"),
    "已提交 Git": ("commit", "success"), "Git 提交已创建": ("commit", "success"),
    "已推送到远端": ("push", "success"), "Git Push 已成功": ("push", "success"),
    "已发布 Beta": ("beta", "success"), "Beta 部署失败": ("beta", "failed"),
    "验收通过": ("acceptance", "success"), "验收未通过": ("acceptance", "failed"),
}
HINT = re.compile(r"(?:下一步|待办|阻塞)\s*[:：]\s*(.+)")
HINTS = {
    "补跑本地测试": "test", "补齐测试用例": "test", "复核本地测试结果": "test",
    "提交 Git": "commit", "推送到远端": "push",
    "检查 Beta 发布状态": "beta", "确认 Beta 部署结果": "beta", "等待测试反馈": "acceptance",
}


def plain_lines(text):
    if not isinstance(text, str) or len(text) > 8192:
        return
    fence = None
    for raw in text.splitlines():
        if raw.startswith(("    ", "\t")):
            continue
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            marker = line[0]
            if fence is None:
                fence = marker
            elif fence == marker and not line.strip(marker).strip():
                fence = None
            continue
        if not fence and line and not line.startswith(">"):
            yield line


def work_key(value):
    if len(value) > 240:
        return None
    if TICKET.fullmatch(value):
        return value
    try:
        url = urlsplit(value)
        host = url.netloc.lower()
    except ValueError:
        return None
    if url.scheme != "https" or not re.fullmatch(r"[a-z0-9.-]+(?::[0-9]{1,5})?", host):
        return None
    path = url.path.rstrip("/")
    if REPO_ISSUE.fullmatch(path) or BROWSE.fullmatch(path):
        return f"https://{host}{path}"
    return None


def user_keys(content):
    if not isinstance(content, list):
        return []
    texts = [part.get("text") for part in content if isinstance(part, dict) and part.get("type") == "text"]
    keys = set()
    for text in texts:
        for line in plain_lines(text):
            match = HEADER.fullmatch(line)
            if match and (key := work_key(match[1])):
                keys.add(key)
    return sorted(keys)


def assistant_signals(text):
    claims, hints = set(), set()
    for line in plain_lines(text):
        label = re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", line).rstrip("。.")
        if label in CLAIMS:
            claims.add(CLAIMS[label])
        match = HINT.fullmatch(label)
        if match and match[1] in HINTS:
            hints.add((HINTS[match[1]], match[1]))
    return sorted(claims), sorted(hints)
