# Agent Flight Recorder — 検証記録（2026-10-12）

## 対象と結果

基準コミット：`b56e8c372d1034c9f83c8c6591fda6ecc2cac08f`。
Python 3.12.14、フォークの `agent-framework-core==1.19.0`、pytest 9.1.1、Ruff 0.16.10。
既存49件＋追加39件、**88件が合格（skipなし）**。Ruff check / format、git diff --checkも合格。
既存の模擬demoと独立Recorder付きの人間用コンソール起動・終了を確認した。
実サービス、実アカウント、LLM API、メール、外部Exporterには接続していない。

Layer 1/2の取得元原本を確認し、CRLF→LFと末尾改行の差を除いて版固定コピーと文言が一致した。
取得時のGitHub Blob SHAはLayer 1が `6996ea58c78c18297cae4bf65499265f2eaa3bd9`、
Layer 2が `182eee68299885d0ba4666aedd2e58091f1d0abd`。原文・manifest・研究Policyは変更していない。

## 必須8要件の確認

| 要件 | 観測結果 |
|---|---|
| 1 正常処理が記録される | 別Recorderプロセスの要求→提案→承認→権限許可→開始→検証成功を確認。実行/Agent/Task/Tool/承認IDが一致 |
| 2 未承認操作の拒否 | Handler呼出しゼロ、拒否イベントあり |
| 3 承認内容と実行内容の不一致 | 引数変更・虚偽の5W1Hを拒否。Handler呼出しゼロ |
| 4 記録障害時の停止 | 要求/権限/開始の各記録失敗でHandler呼出しゼロ。結果記録失敗時は成功を返さずラッチ停止 |
| 5 Agentによる監査変更を拒否 | Tokenなしのappend/read/edit/deleteを拒否。seccomp付きの独立Planner子プロセスで直接読取/書込/削除をOSが拒否 |
| 6 Prompt Injectionで権限拡大しない | 文字列中の偽承認・ログ削除命令はデータ。偽の所有者権限・未知のShell Toolも拒否 |
| 7 Tool異常終了を成功にしない | 例外・タイムアウト・取消しはRESULT_UNKNOWN、Verifier不成立はUNVERIFIED。秘密を含む例外本文を保存しない |
| 8 データ引き渡しの追跡 | 検証済み出力Digestとsource/destination IDを記録。改変コピーを拒否、宛先で改めて承認が必要 |

## 追加で確認した条件

- 同時提案で未処理一件制限を超えない。同時実行で一つの承認からHandlerが二度動かない。
- 複数Writerが同じStoreを開けない。改変・切捨て・欠損・不正署名・鍵相違を拒否。
- Log保存とCheckpoint更新の間の障害で、勝手な修復・起動続行をしない。
- 停止はRecorder障害中でもローカルに保持。実行中の端末操作から協調停止を確認。
- 未完了開始を再起動後に結果不明として記録。内部台帳だけCOMPLETEDでも独立結果がなければ保留。
- 人間照合の追加は承認・予算・実行を復活させない。古いセッションの承認は実行できない。
- 生の入力/出力・例外・任意の秘密Fieldを記録しない。
- SDKの実際のAgent loopが5W1H付き提案を生成し、提案だけで操作が実行されない。
- Tracer未設定でも監査が残る。有効なOTel contextがあればTrace/Span IDが関連付く。

## 未検証・解釈の限界

この結果は、サポートした模擬経路の試験。全既存SDKの迂回経路を閉鎖したという証明ではない。
UNIX Socketは環境制限で作成できず、end-to-end試験は行えていない。peer認可の拒否ロジックだけ試験した。
パイプモードは別の実プロセスで試験したが同一UIDの開発構成。別UIDのsystemd構成例は未配置・未検証。

Landlockは環境で利用不能（ENOSYS）。不成立時の拒否を試験したが、Landlockが有効な場合の正常パスは未検証。
メモリ内処理だけのseccompモードでは、子Plannerの監査ファイル直接アクセスの拒否を実測した。
Socketは環境側でも拒否されるため、ネットワーク拒否が独自Filterだけの効果であることは分離検証していない。

UI試験は操作の反映を確認したもの。所有者本人の理解・検討の実地試験や本人認証は未完了。
通常のTracingの全設定について機密漏洩がないこと、実サービス効果、外部停止確認、WORM保全は未検証・未実装。
監査通信は10秒でタイムアウトし、その後Clientを再利用しない。同期監査中のUI応答は遅れる場合があり、
この時間内のOS/supervisorによる強制停止は今回未実装。設定例を配備すれば安全という保証ではない。

GitHub Actionsの既存workflowはPRの `agent_factory/**` 差分で同じ試験を実施する設定。
本記録はローカルで観測した結果であり、リモートCIの合格を宣言するものではない。

## 追加・変更ファイル

| ファイル（全てagent_factory配下） | 内容 |
|---|---|
| `human_agent_governance/flight_recorder/__init__.py` | 独立拡張の公開入口 |
| `flight_recorder/client.py`（同パッケージ配下） | Pipe/UNIX Socket Client、照合ID、故障時の遮断 |
| `flight_recorder/service.py` | 別プロセスの受付、Token/UID、Schema制限 |
| `flight_recorder/store.py` | HMAC Chain、fsync、独立Checkpoint、Writer lock |
| `flight_recorder/gateway.py` | 既存統制の再利用、5W1H照合、記録必須の実行、停止/照合/handoff |
| `flight_recorder/framework.py` | 既存SDKガードを使うオフラインAgentアダプター |
| `flight_recorder/dashboard.py` | 人間用の時系列・詳細・承認・実行中停止コンソール |
| `flight_recorder/sandbox.py` | Linux x86_64 seccomp、Landlock（正常パス未検証） |
| `flight_recorder/demo.py` | ダミーデータの手動承認demo |
| `tests/test_flight_recorder.py` | 必須8要件と障害・競合・OS制限・SDK接続の39ケース |
| `deploy/flight-recorder/recorder.service.example` | Recorder用未配備の別UID設定案 |
| `deploy/flight-recorder/gateway.service.example` | Gateway用未配備の別UID設定案 |
| `deploy/flight-recorder/planner.service.example` | Planner用未配備の権限制限案 |
| `docs/FLIGHT_RECORDER.md` | 設計、運用、復旧、記録範囲、残存リスク |
| `docs/FLIGHT_RECORDER_VALIDATION.md` | この検証記録 |
| `README.md`（変更） | 追加経路と文書への案内 |
| `.gitignore`（変更） | 実行ログ・鍵・Checkpoint等のGit混入防止 |
