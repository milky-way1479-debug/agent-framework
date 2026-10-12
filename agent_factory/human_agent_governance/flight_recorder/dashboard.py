"""Trusted-owner terminal dashboard. No HTTP server, remote auth or automatic execution."""

from __future__ import annotations

import asyncio
import json

from ..policy import GovernanceError

LABELS = {
    "PENDING": "承認待ち",
    "APPROVED": "承認済み",
    "RUNNING": "実行中・停止未確認",
    "COMPLETED": "成功（検証済み）",
    "UNVERIFIED": "検証失敗",
    "RESULT_UNKNOWN": "異常停止・結果不明",
    "DENIED": "拒否",
    "REJECTED": "人間が拒否",
    "CANCELLED": "取消し",
    "STOPPED": "新規開始を停止",
    "FAILED": "失敗（人間照合）",
    "NOT_STARTED": "未実行（人間照合）",
}


class MonitoringDashboard:
    """Only the owner-controlling terminal gets this instance or its authority."""

    def __init__(self, gateway, authority):
        gateway._owner(authority)
        self.gateway, self.authority = gateway, authority
        self._running = {}

    def timeline(self):
        # Independent store verifies its chain/checkpoint before returning any row.
        return self.gateway.recorder.read()

    def detail(self, operation_id):
        return [r for r in self.timeline() if r["payload"].get("execution_id") == operation_id]

    def decide(self, operation_id, approved):
        self.gateway.decide(operation_id, approved, self.authority)

    def stop(self, task_id):
        self.gateway.stop(task_id, self.authority)

    async def _execute(self, identifier, arguments, write):
        try:
            report = await self.gateway.execute(identifier, arguments)
            write(LABELS[report.status])
        except GovernanceError:
            write("実行を保留しました。成功とは扱わず、履歴と結果を照合してください。")
        finally:
            self._running.pop(identifier, None)

    async def run(self, read=input, write=print):
        while True:
            write("\nAgent Flight Recorder / OFFLINE MOCK / 人間用コンソール")
            try:
                for row in self.timeline():
                    p = row["payload"]
                    write(
                        f"{row['seq']:04d} {p['timestamp']:.3f} {p['event']} "
                        f"{LABELS.get(p.get('status'), '')} {p.get('execution_id', '')}"
                    )
            except GovernanceError:
                write("監査を確認できません。実行禁止。stopは引き続き使用できます。")
            command = await asyncio.to_thread(
                read, "detail/review/approve/reject/execute <操作ID>, stop <TaskID>, quit > "
            )
            verb, _, identifier = command.partition(" ")
            try:
                if verb == "quit":
                    # Exit is not authorization to leave a tool running without supervision.
                    running = list(self._running.values())
                    for identifier in list(self._running):
                        pending = self.gateway._pending.get(identifier)
                        if pending:
                            try:
                                self.stop(pending["task_id"])
                            except GovernanceError:
                                write("停止はローカルに保持しました。記録・実停止は未確認です。")
                    for job in running:
                        job.cancel()
                    await asyncio.gather(*running, return_exceptions=True)
                    return
                if verb == "detail":
                    write(json.dumps(self.detail(identifier), ensure_ascii=False, indent=2))
                elif verb == "review":
                    write(
                        json.dumps(
                            self.gateway.preview(identifier, self.authority), ensure_ascii=False, indent=2
                        )
                    )
                elif verb in {"approve", "reject"}:
                    # Show exact arguments, 5W1H, verification, limits before asking for a decision.
                    write(
                        json.dumps(
                            self.gateway.preview(identifier, self.authority), ensure_ascii=False, indent=2
                        )
                    )
                    decision = await asyncio.to_thread(read, "この操作を承認しますか？ YES / NO > ")
                    if decision == ("YES" if verb == "approve" else "NO"):
                        self.decide(identifier, verb == "approve")
                elif verb == "execute":
                    preview = self.gateway.preview(identifier, self.authority)
                    if identifier in self._running:
                        raise GovernanceError("Operation already in progress")
                    self._running[identifier] = asyncio.create_task(
                        self._execute(identifier, preview["arguments"], write)
                    )
                    write("実行を開始します。実行中も stop <TaskID> を受け付けます。")
                elif verb == "stop":
                    self.stop(identifier)
                    write("新規開始を停止しました。進行中Toolは協調停止と結果照合が必要です。")
                else:
                    write("コマンドを確認してください。")
            except (GovernanceError, KeyError):
                write("操作を保留しました。監査履歴と承認・実行条件を確認してください。")
